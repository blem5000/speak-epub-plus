"""Local offline TTS via Piper (CPU, no network) — optional engine next to Edge TTS.

Voice models (.onnx + .onnx.json, ~63–115 MB each) live under
``<user>/Documents/speak-epub/models/piper`` (override: SPEAK_EPUB_MODELS_DIR)
and are downloaded on demand from the official rhasspy/piper-voices repo.

Design notes:
- heavy deps (piper / onnxruntime) are imported lazily so Edge-only runs and
  app startup never pay for them
- synthesis happens fully offline; part MP3s are encoded with ffmpeg at the
  same 48k mono profile as Edge output, so resume/verify/merge stay identical
  (a single profile matters: parts are merged with ``-c copy``, which cannot
  mix bitrates)
- ``rate`` keeps its Edge meaning ("+25%" = 1.25x speed) and maps onto Piper's
  ``length_scale``; the effective speed is clamped to 0.75–2.0, and the
  duration-based verification scales its floor with the requested rate so
  complete fast parts are not mistaken for truncation
"""
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from core.tts import normalize_tts_rate, verify_part_audio

#: Auto mode picks the local engine only on machines with at least this many
#: logical CPUs (below that, ONNX synthesis is slower than Edge download).
LOCAL_MIN_CORES = 8

#: Hard ceiling for local synthesis workers (CPU-bound; more adds little).
LOCAL_MAX_WORKERS = 8

#: Curated, tested voices exposed in the UI. download_voice() resolves the
#: real files from voices.json — keep names exactly as published there.
LOCAL_VOICES: Dict[str, Dict[str, Any]] = {
    "en_US-lessac-medium": {"lang": "en", "quality": "medium", "size_mb": 63},
    "en_US-ryan-high": {"lang": "en", "quality": "high", "size_mb": 115},
    "en_GB-alan-medium": {"lang": "en", "quality": "medium", "size_mb": 63},
    "pl_PL-darkman-medium": {"lang": "pl", "quality": "medium", "size_mb": 63},
    "pl_PL-gosia-medium": {"lang": "pl", "quality": "medium", "size_mb": 63},
}

DEFAULT_LOCAL_VOICE = "en_US-lessac-medium"

#: Socket timeout (s) for voice-model downloads — piper's own downloader has
#: none, and a stalled connection would block the sequential sidecar RPC
#: loop forever.
_DOWNLOAD_TIMEOUT_SEC = 30

#: Overall deadline (s) for a single voice-file download: the socket timeout
#: above fires per read, but a trickling connection could otherwise stall
#: just under it forever.
_DOWNLOAD_TOTAL_TIMEOUT_SEC = 600

#: Progress logLines are emitted every this many bytes during download (the
#: only download telemetry until the UI subscribes to progress events).
_DOWNLOAD_PROGRESS_EVERY = 10 * 1024 * 1024

_VOICE_CACHE: Dict[str, Any] = {}
_VOICE_LOCK = threading.Lock()

#: Directory holding the optional local-engine tier (Piper + numpy +
#: onnxruntime). It is a SEPARATE download: the runtime tier carries only
#: the core dependencies, so the app stays small and the local engine is
#: fetched only when the user actually turns it on.
_LOCAL_ENGINE_DIR_NAME = "local"

#: Progress logLines are emitted every this many bytes during download.
_LOCAL_ENGINE_PROGRESS_EVERY = 10 * 1024 * 1024

#: Socket timeout (s) for the local-engine download.
_LOCAL_ENGINE_TIMEOUT_SEC = 30

#: Overall deadline (s) for the local-engine download.
_LOCAL_ENGINE_TOTAL_TIMEOUT_SEC = 900


def local_engine_root() -> Path:
    """Directory holding the optional local-engine tier (env override for tests)."""
    env = os.environ.get("SPEAK_EPUB_LOCAL_ENGINE_DIR")
    if env:
        return Path(env)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / "speak-epub" / _LOCAL_ENGINE_DIR_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "speak-epub" / _LOCAL_ENGINE_DIR_NAME
    return Path.home() / ".local" / "share" / "speak-epub" / _LOCAL_ENGINE_DIR_NAME


def _runtime_descriptor() -> Dict[str, Any]:
    """Read `runtime.json` (written next to the app tier by the release build).

    The sidecar runs with its working directory set to the app tier's
    `code` folder, so the descriptor sits one level up.
    """
    candidates = [
        Path.cwd() / "runtime.json",
        Path.cwd().parent / "runtime.json",
        # the sidecar's code dir sits next to the descriptor:
        # <app tier>/sidecar-runtime/code/core/tts_local.py -> ../../runtime.json
        Path(__file__).resolve().parent.parent.parent / "runtime.json",
        Path(__file__).resolve().parent.parent / "runtime.json",
    ]
    for path in candidates:
        try:
            if path.is_file():
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        except Exception:
            continue
    return {}


def local_engine_available() -> bool:
    """True when the Piper engine can be imported right now."""
    if _local_engine_site() is not None:
        return True
    try:
        importlib.import_module("piper")  # noqa: F401
        importlib.import_module("onnxruntime")  # noqa: F401
        return True
    except Exception:
        return False


def _local_engine_site() -> Optional[Path]:
    """The cached local-engine directory, when it holds a usable piper."""
    descriptor = _runtime_descriptor()
    local_hash = descriptor.get("local_hash") if descriptor else None
    if not isinstance(local_hash, str) or not local_hash:
        return None
    site = local_engine_root() / local_hash
    if (site / "piper").is_dir():
        return site
    return None


def _add_local_engine_to_path() -> None:
    """Put the cached local-engine directory on sys.path (if present)."""
    site = _local_engine_site()
    if site is None:
        return
    path = str(site)
    if path not in sys.path:
        sys.path.insert(0, path)


def ensure_local_engine(on_log: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Make the Piper engine usable — downloads the local-engine tier once.

    The runtime tier ships only the core dependencies; Piper, numpy and
    onnxruntime (~60 MB) are a separate optional download, fetched the
    first time the user turns the local engine on. Returns
    {"ok": bool, "downloaded": bool, "message": str}.
    """
    def _log(line: str) -> None:
        if on_log is not None:
            try:
                on_log(line)
            except Exception:
                pass

    if local_engine_available():
        _add_local_engine_to_path()
        return {"ok": True, "downloaded": False, "message": "local engine ready"}

    descriptor = _runtime_descriptor()
    asset = descriptor.get("local_asset")
    release_url = descriptor.get("release_url")
    local_hash = descriptor.get("local_hash")
    if not (isinstance(asset, str) and asset and isinstance(release_url, str) and release_url):
        _log("the local engine is not available in this build")
        return {
            "ok": False,
            "downloaded": False,
            "message": "the local engine components are not part of this build",
        }

    target = local_engine_root() / str(local_hash)
    marker = target / ".ready"
    if not marker.is_file():
        url = f"{release_url.rstrip('/')}/{asset}"
        _log(f"downloading the local TTS engine ({asset})…")
        try:
            _download_and_extract(url, target, _log)
        except Exception as e:
            _log(f"local engine download failed: {e}")
            return {"ok": False, "downloaded": False, "message": f"download failed: {e}"}
        try:
            marker.write_text("ok", encoding="utf-8")
        except OSError:
            pass
    _add_local_engine_to_path()
    if not local_engine_available():
        return {
            "ok": False,
            "downloaded": False,
            "message": "the local engine components were extracted but piper is still missing",
        }
    _log("local TTS engine ready")
    return {"ok": True, "downloaded": True, "message": "local engine downloaded"}


def _download_and_extract(url: str, target: Path, on_log: Optional[Callable[[str], None]] = None) -> None:
    """Download a zip asset and extract it into `target` (atomically)."""
    import urllib.request
    import zipfile

    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.parent / f".staging-{target.name}-{os.getpid()}"
    try:
        if staging.exists():
            import shutil as _shutil

            _shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True, exist_ok=True)
        archive = staging / "asset.zip"
        req = urllib.request.Request(url, headers={"User-Agent": "speak-epub/1 (local engine)"})
        total = 0
        with urllib.request.urlopen(req, timeout=_LOCAL_ENGINE_TIMEOUT_SEC) as resp:
            length = resp.headers.get("Content-Length")
            try:
                total = int(length or 0)
            except (TypeError, ValueError):
                total = 0
            with open(archive, "wb") as f:
                while True:
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(staging)
        try:
            archive.unlink()
        except OSError:
            pass
        # the archive root holds the packages themselves
        import shutil as _shutil

        if target.exists():
            _shutil.rmtree(target, ignore_errors=True)
        _shutil.move(str(staging), str(target))
    finally:
        import shutil as _shutil

        _shutil.rmtree(staging, ignore_errors=True)


def local_models_root() -> Path:
    """Directory holding downloaded Piper voices (env override for tests)."""
    env = os.environ.get("SPEAK_EPUB_MODELS_DIR")
    if env:
        return Path(env)
    from core.tts import user_output_base

    return user_output_base() / "models" / "piper"


def _piper_available() -> bool:
    """True when the local engine can actually be used.

    The engine components (Piper + numpy + onnxruntime) are a separate
    optional download; they are imported here (and cached on sys.path).
    """
    _add_local_engine_to_path()
    try:
        importlib.import_module("piper")  # noqa: F401
        importlib.import_module("onnxruntime")  # noqa: F401
        return True
    except Exception:
        return False


def validate_local_voice(voice: Any) -> str:
    """Return a curated voice id or raise ValueError."""
    if isinstance(voice, str):
        wanted = voice.strip()
        if wanted in LOCAL_VOICES:
            return wanted
    raise ValueError(f"unknown local voice {voice!r} (choose one of: {', '.join(LOCAL_VOICES)})")


def local_voice_paths(voice: str) -> tuple[Path, Path]:
    root = local_models_root()
    return root / f"{voice}.onnx", root / f"{voice}.onnx.json"


def _model_digest_path(voice: str) -> Path:
    """Sidecar with the sha256 of the downloaded model (integrity check)."""
    onnx, _ = local_voice_paths(voice)
    return onnx.with_suffix(onnx.suffix + ".sha256")


def _file_sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _model_integrity_ok(voice: str) -> bool:
    """Verify the model against the digest recorded at download time.

    The publisher offers no checksums, so the digest is computed locally
    after the download — it catches a truncated or swapped model file (the
    ONNX loader would fail much later with a cryptic error).
    """
    onnx, _ = local_voice_paths(voice)
    digest_path = _model_digest_path(voice)
    try:
        if not digest_path.is_file():
            return True  # nothing recorded (an old download) — size check only
        expected = digest_path.read_text(encoding="utf-8").strip().split()[0]
        if len(expected) != 64:
            return True
        return _file_sha256(onnx) == expected
    except (OSError, IndexError):
        return True
    except Exception:
        return True


def local_voice_ready(voice: Any) -> bool:
    """True when the model files are downloaded AND piper is importable."""
    if not isinstance(voice, str) or voice.strip() not in LOCAL_VOICES:
        return False
    onnx, cfg = local_voice_paths(voice.strip())
    try:
        if not (onnx.is_file() and cfg.is_file()):
            return False
        if onnx.stat().st_size < 1_000_000:
            return False
        # the config drives the phonemizer: a truncated/empty one would only
        # blow up inside PiperVoice.load, long after "downloaded" was shown
        if cfg.stat().st_size < 64:
            return False
    except OSError:
        return False
    if not _model_integrity_ok(voice.strip()):
        return False
    return _piper_available()


def list_local_voices() -> Dict[str, Any]:
    """Status payload for the Settings UI: curated voices + downloaded state."""
    root = local_models_root()
    voices = []
    for name, meta in LOCAL_VOICES.items():
        onnx, _ = local_voice_paths(name)
        try:
            size_bytes = onnx.stat().st_size if onnx.is_file() else 0
        except OSError:
            size_bytes = 0
        voices.append(
            {
                "id": name,
                "lang": meta["lang"],
                "quality": meta["quality"],
                "sizeMb": meta["size_mb"],
                "downloaded": local_voice_ready(name),
                "bytes": size_bytes,
            }
        )
    return {
        "modelsDir": str(root),
        "default": DEFAULT_LOCAL_VOICE,
        "voices": voices,
        "piperAvailable": _piper_available(),
    }


def download_local_voice(voice: Any, on_log: Optional[Callable[[str], None]] = None, force: bool = False) -> Dict[str, Any]:
    """Download a curated voice into the models dir; returns its status dict.

    Downloads stream with a socket timeout (plus an overall deadline) into a
    staging directory and are published atomically (os.replace), so an
    interrupted download can never leave a partial .onnx that
    `local_voice_ready` would accept as installed. `force=True` re-downloads
    even when files are present; the old files stay in place until the staged
    replacements publish, so a failed re-download never leaves no voice.
    """

    def _log(msg: str) -> None:
        if on_log:
            try:
                on_log(msg)
            except Exception:
                pass

    name = validate_local_voice(voice)
    if not _piper_available():
        raise RuntimeError("piper-tts is not installed — local voices unavailable in this build")

    root = local_models_root()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise RuntimeError(f"cannot create models directory {root}: {e}") from e

    onnx, cfg = local_voice_paths(name)
    if local_voice_ready(name) and not force:
        _log(f"local voice {name} already downloaded")
    else:
        size_mb = LOCAL_VOICES[name]["size_mb"]
        _log(f"downloading local voice {name} (~{size_mb} MB)...")
        model_url, config_url = _voice_download_urls(name)
        # drop orphaned staging dirs from crashed earlier runs (same voice)
        for _stale in root.glob(f".staging-{name}-*"):
            try:
                if _stale.is_dir():
                    shutil.rmtree(_stale, ignore_errors=True)
                else:
                    _stale.unlink(missing_ok=True)
            except Exception:
                pass
        staging = Path(tempfile.mkdtemp(prefix=f".staging-{name}-", dir=str(root)))
        try:
            _fetch_to_file(model_url, staging / onnx.name, name, _log)
            _fetch_to_file(config_url, staging / cfg.name, name, _log)
            os.replace(staging / onnx.name, onnx)
            try:
                os.replace(staging / cfg.name, cfg)
            except Exception:
                # never leave a mixed new-onnx/old-config pair behind: it
                # would pass the ready check and fail only at synthesis
                try:
                    onnx.unlink(missing_ok=True)
                except Exception:
                    pass
                raise
        except Exception as e:
            raise RuntimeError(f"failed to download local voice {name}: {e}") from e
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        if not local_voice_ready(name):
            raise RuntimeError(f"download finished but model files are incomplete for {name}")
        # record the digest of the model: the publisher offers no checksum,
        # so a local digest catches a truncated or swapped file later
        try:
            _model_digest_path(name).write_text(
                f"{_file_sha256(onnx)}  {onnx.name}\n", encoding="utf-8"
            )
        except OSError:
            pass
        _log(f"local voice {name} downloaded")
    return {
        "id": name,
        "modelsDir": str(root),
        "path": str(onnx),
        "bytes": onnx.stat().st_size,
    }


def _voice_download_urls(voice: str) -> tuple[str, str]:
    """Resolve (.onnx, .onnx.json) URLs from piper's official URL_FORMAT."""
    try:
        from piper.download_voices import URL_FORMAT, VOICE_PATTERN
    except ImportError as e:
        raise RuntimeError(
            f"incompatible piper-tts version: cannot resolve voice download URLs ({e})"
        ) from e

    m = VOICE_PATTERN.match(voice.strip())
    if not m:
        raise ValueError(f"local voice {voice!r} does not match the piper voice naming scheme")
    parts = {
        "lang_family": m.group("lang_family"),
        "lang_code": f"{m.group('lang_family')}_{m.group('lang_region')}",
        "voice_name": m.group("voice_name"),
        "voice_quality": m.group("voice_quality"),
    }
    return (
        URL_FORMAT.format(extension=".onnx", **parts),
        URL_FORMAT.format(extension=".onnx.json", **parts),
    )


def _fetch_to_file(url: str, dest_tmp: Path, label: str, log_fn: Callable[[str], None]) -> None:
    """Stream a URL to a temp file with timeouts, logging progress.

    Raises RuntimeError on network errors, overall-deadline expiry, empty
    responses, and short bodies (declared Content-Length unmet) — a truncated
    download must never be mistaken for a complete voice file.
    """
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "speak-epub/1.0"})
    done = 0
    total: Optional[int] = None
    next_mark = _DOWNLOAD_PROGRESS_EVERY
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=_DOWNLOAD_TIMEOUT_SEC) as resp:
            try:
                _length = resp.headers.get("Content-Length")
                total = int(_length) if _length else None
            except Exception:
                total = None
            try:
                total_mb = total // (1024 * 1024) if total else None
            except Exception:
                total_mb = None
            with open(dest_tmp, "wb") as f:
                while True:
                    if time.monotonic() - started > _DOWNLOAD_TOTAL_TIMEOUT_SEC:
                        raise RuntimeError(
                            f"download timed out after {_DOWNLOAD_TOTAL_TIMEOUT_SEC}s for {label}"
                        )
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if done >= next_mark:
                        next_mark = done + _DOWNLOAD_PROGRESS_EVERY
                        tail = f" of ~{total_mb} MB" if total_mb else ""
                        log_fn(f"downloading {label}: {done // (1024 * 1024)} MB{tail}...")
    except Exception as e:
        try:
            dest_tmp.unlink(missing_ok=True)
        except Exception:
            pass
        raise RuntimeError(f"download failed for {label}: {e}") from e
    if done <= 0:
        try:
            dest_tmp.unlink(missing_ok=True)
        except Exception:
            pass
        raise RuntimeError(f"download failed for {label}: empty response")
    if total is not None and done < total:
        try:
            dest_tmp.unlink(missing_ok=True)
        except Exception:
            pass
        raise RuntimeError(
            f"download failed for {label}: incomplete body ({done} of {total} bytes)"
        )


def _local_unavailable_message(voice: str) -> str:
    """Distinguish a missing model from a missing piper install for errors."""
    onnx, cfg = local_voice_paths(voice)
    try:
        files_ok = onnx.is_file() and cfg.is_file() and onnx.stat().st_size >= 1_000_000
    except OSError:
        files_ok = False
    if not files_ok:
        return f"local voice not downloaded: {voice} (download it in Settings first)"
    if not _piper_available():
        return f"piper-tts is not installed in this build — local voice {voice} is unavailable"
    return f"local voice not downloaded: {voice} (download it in Settings first)"


def resolve_engine(engine: Any, local_voice: Any = None) -> str:
    """Resolve the requested engine ('auto'|'edge'|'local') to 'edge' or 'local'.

    - edge   → always Edge
    - local  → Piper; raises ValueError when the model is not downloaded
    - auto   → Piper when this machine is fast enough (>= LOCAL_MIN_CORES) and
      the selected voice model is present; otherwise Edge
    """
    eng = engine.strip().lower() if isinstance(engine, str) else "auto"
    if eng not in ("auto", "edge", "local"):
        eng = "auto"
    if eng == "edge":
        return "edge"
    voice = local_voice if isinstance(local_voice, str) and local_voice.strip() else DEFAULT_LOCAL_VOICE
    if eng == "local":
        validate_local_voice(voice)
        if not local_voice_ready(voice):
            raise ValueError(_local_unavailable_message(voice))
        return "local"
    cores = os.cpu_count() or 0
    if local_voice_ready(voice) and cores >= LOCAL_MIN_CORES:
        return "local"
    return "edge"


def effective_local_parallel() -> int:
    """Worker count for local synthesis: CPU-bound, clamped to 1..LOCAL_MAX_WORKERS."""
    try:
        cores = os.cpu_count() or 4
    except Exception:
        cores = 4
    return max(1, min(int(cores), LOCAL_MAX_WORKERS))


def rate_to_length_scale(rate: Any) -> float:
    """Edge-style rate ('+25%') → Piper length_scale (1/1.25), speed clamped 0.75–2.0.

    The clamp matches the Edge range (-100%..+100%) so the same setting does
    not produce different audio per engine: below -25% the local engine used
    to saturate while Edge kept slowing down.
    """
    normalized = normalize_tts_rate(rate)
    try:
        num = int(normalized.rstrip("%"))
    except Exception:
        num = 0
    num = max(-100, min(100, num))
    speed = max(0.75, min(2.0, 1.0 + num / 100.0))
    return 1.0 / speed


class _TruncatedLocalError(RuntimeError):
    """Internal: local synth produced a complete-but-short file (deterministic)."""


def cuda_available() -> bool:
    """True when the installed onnxruntime can use the GPU.

    The CUDA execution provider only exists in the `onnxruntime-gpu` wheel;
    the CPU wheel reports CPUExecutionProvider only.
    """
    try:
        import onnxruntime

        providers = list(onnxruntime.get_available_providers())
    except Exception:
        return False
    return any("CUDA" in p or "Tensorrt" in p for p in providers)


def cuda_requested() -> bool:
    """Did the user ask for the GPU? (env var or the store flag)."""
    env = os.environ.get("SPEAK_EPUB_PIPER_CUDA", "").strip().lower()
    if env in ("1", "true", "yes", "on"):
        return True
    if env in ("0", "false", "no", "off"):
        return False
    try:
        from core.config import load_store

        return bool(load_store().get("localCuda", False))
    except Exception:
        return False


def _load_voice(voice: str):
    with _VOICE_LOCK:
        cached = _VOICE_CACHE.get(voice)
        if cached is not None:
            return cached
        onnx, _ = local_voice_paths(voice)
        from piper import PiperVoice

        use_cuda = False
        if cuda_requested():
            if cuda_available():
                use_cuda = True
            else:
                print(
                    "Warning: the GPU was requested but onnxruntime has no CUDA provider "
                    "(install onnxruntime-gpu) — using the CPU."
                )
        try:
            loaded = PiperVoice.load(str(onnx), use_cuda=use_cuda)
        except Exception as e:
            if use_cuda:
                # the GPU failed to initialise (no CUDA runtime/driver) — fall
                # back to the CPU instead of failing the whole part
                print(f"Warning: the GPU engine failed ({e}) — falling back to the CPU.")
                loaded = PiperVoice.load(str(onnx), use_cuda=False)
            else:
                raise
        _VOICE_CACHE[voice] = loaded
        return loaded


def tts_text_to_mp3_local(
    text: str,
    output_path: str,
    voice: str,
    retries: int = 5,
    rate: Optional[str] = None,
    ffmpeg_bin: str = "ffmpeg",
    on_retry: Optional[Callable[[int, Exception], None]] = None,
) -> None:
    """Synthesize `text` fully offline into an MP3 part (48k mono, like Edge).

    Synchronous like the Piper API itself. Transient synthesis/encoding
    failures (file locks, flaky disk) are retried with backoff using
    `retries`, mirroring tts_text_to_mp3; a "truncated" verification verdict
    raises immediately (deterministic for the same text/voice/rate, so
    retries can't help).
    """
    name = validate_local_voice(voice)
    if not local_voice_ready(name):
        raise RuntimeError(_local_unavailable_message(name))
    if not _piper_available():
        # the engine components are an optional download — fetch them once
        result = ensure_local_engine()
        if not result.get("ok"):
            raise RuntimeError(
                "the local TTS engine is not installed in this build — "
                "use the Edge engine or install the local components"
            )

    try:
        retries = int(retries)
        if retries < 1:
            retries = 1
    except Exception:
        retries = 5

    output = Path(output_path)
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        # a permission problem must surface here, not as a cryptic ffmpeg
        # error later ("No such file or directory")
        raise RuntimeError(f"cannot create the output directory {output.parent}: {e}") from e
    wav_path = output.with_suffix(".part.wav")

    # deterministic pre-checks stay outside the retry loop: a missing binary
    # cannot heal between attempts; self-heal downloads a portable build once
    ffmpeg = shutil.which(ffmpeg_bin)
    if not ffmpeg:
        from core.ffmpeg_setup import ensure_ffmpeg

        ensure_ffmpeg()
        ffmpeg = shutil.which(ffmpeg_bin)
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found on PATH — required for local TTS MP3 encoding")

    for attempt in range(1, retries + 1):
        try:
            from piper import SynthesisConfig

            piper_voice = _load_voice(name)
            syn_config = SynthesisConfig(length_scale=rate_to_length_scale(rate))
            with wave.open(str(wav_path), "wb") as wf:
                piper_voice.synthesize_wav(text, wf, syn_config=syn_config)

            proc = subprocess.run(
                [
                    ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                    "-i", str(wav_path),
                    "-codec:a", "libmp3lame", "-b:a", "48k", "-ac", "1", "-ar", "24000",
                    str(output),
                ],
                capture_output=True,
                timeout=600,
            )
            if proc.returncode != 0 or not output.is_file():
                stderr = (proc.stderr or b"").decode("utf-8", "replace")[-400:]
                # a failed encode must not leave a truncated mp3 behind: resume
                # would have to detect and drop it on the next run anyway
                try:
                    output.unlink(missing_ok=True)
                except Exception:
                    pass
                raise RuntimeError(f"ffmpeg failed to encode local TTS output: {stderr}")

            ok, reason = verify_part_audio(str(output), text, rate=rate)
            if ok:
                return
            try:
                output.unlink(missing_ok=True)
            except Exception:
                pass
            if reason == "truncated":
                raise _TruncatedLocalError(
                    f"local TTS output truncated for {output.name} "
                    f"({len(text)} chars) — try a lower rate or shorter text"
                )
            raise RuntimeError(f"local TTS produced invalid audio ({reason}) for {output.name}")
        except _TruncatedLocalError:
            raise
        except Exception as e:
            # clean partial file left by a failed attempt so resume never reuses it
            try:
                if output.is_file():
                    output.unlink(missing_ok=True)
            except Exception:
                pass
            if attempt < retries:
                print(f"        retry {attempt}/{retries - 1} for {output.name}: {e}")
                if on_retry is not None:
                    try:
                        on_retry(attempt, e)
                    except Exception:
                        pass
                time.sleep(min(20, 2 * attempt))
                continue
            raise RuntimeError(f"local TTS failed after {retries} attempts for {output.name}: {e}") from e
        finally:
            try:
                wav_path.unlink(missing_ok=True)
            except Exception:
                pass
