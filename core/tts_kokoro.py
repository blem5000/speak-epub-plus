"""Local offline TTS via Kokoro-82M (ONNX) — optional engine next to Edge/Piper.

The model (`kokoro-v1.0.onnx`, ~310 MB) and the voice pack
(`voices-v1.0.bin`, ~27 MB) are a separate on-demand download, exactly like
Piper voice models: the engine *packages* ship in their own tier, the weights
are fetched when the user picks a voice.

Design notes:
- `kokoro_onnx` / `onnxruntime` are imported lazily so Edge-only runs and app
  startup never pay for them
- synthesis is fully offline; parts are encoded to the same 48k mono 24 kHz
  MP3 profile as Edge and Piper, so resume/verify/merge stay identical (parts
  are merged with `-c copy`, which cannot mix bitrates)
- unlike seq2seq models with a fixed token budget, Kokoro has no output cap,
  so a full 3500-char chunk synthesizes in one pass without truncation
- `rate` keeps its Edge meaning ("+25%" = 1.25x) and maps onto Kokoro `speed`
"""
import importlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from core.tts import normalize_tts_rate, user_output_base, verify_part_audio

#: Curated, tested male voices exposed in the UI. All four are English; the
#: voice pack also carries the rest of the catalogue, which
#: `validate_kokoro_voice` accepts once the pack is present.
KOKORO_VOICES: Dict[str, Dict[str, Any]] = {
    "am_michael": {"lang": "en-us", "gender": "male", "accent": "US", "note": "calm, measured"},
    "am_puck": {"lang": "en-us", "gender": "male", "accent": "US", "note": "brighter, faster"},
    "bm_daniel": {"lang": "en-gb", "gender": "male", "accent": "UK", "note": "neutral narrator"},
    "bm_george": {"lang": "en-gb", "gender": "male", "accent": "UK", "note": "deepest, audiobook"},
}

DEFAULT_KOKORO_VOICE = "am_michael"

#: File names inside the models directory.
MODEL_FILE = "kokoro-v1.0.onnx"
VOICES_FILE = "voices-v1.0.bin"

#: Upstream weights (the kokoro-onnx v1.0 release assets).
_MODEL_URL = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
    "model-files-v1.0/kokoro-v1.0.onnx"
)
_VOICES_URL = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
    "model-files-v1.0/voices-v1.0.bin"
)

#: Socket timeout (s) and overall deadline for a weights download.
_DL_TIMEOUT_SEC = 30
_DL_TOTAL_TIMEOUT_SEC = 1800
_DL_PROGRESS_EVERY = 20 * 1024 * 1024

_ENGINE_DIR_NAME = "kokoro"

_CACHE: Dict[str, Any] = {}
_CACHE_LOCK = threading.Lock()


def kokoro_engine_root() -> Path:
    """Directory holding the optional Kokoro package tier (env override for tests)."""
    env = os.environ.get("SPEAK_EPUB_KOKORO_ENGINE_DIR")
    if env:
        return Path(env)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / "speak-epub" / _ENGINE_DIR_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "speak-epub" / _ENGINE_DIR_NAME
    return Path.home() / ".local" / "share" / "speak-epub" / _ENGINE_DIR_NAME


def kokoro_models_root() -> Path:
    """Directory holding the downloaded model + voice pack (env override for tests)."""
    env = os.environ.get("SPEAK_EPUB_KOKORO_MODELS_DIR")
    if env:
        return Path(env)
    return user_output_base() / "models" / "kokoro"


def _runtime_descriptor() -> Dict[str, Any]:
    """Read `runtime.json` (written next to the app tier by the release build)."""
    candidates = [
        Path.cwd() / "runtime.json",
        Path.cwd().parent / "runtime.json",
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


def _engine_site() -> Optional[Path]:
    """The cached Kokoro package directory, when it holds a usable kokoro_onnx."""
    descriptor = _runtime_descriptor()
    kh = descriptor.get("kokoro_hash") if descriptor else None
    if not isinstance(kh, str) or not kh:
        return None
    site = kokoro_engine_root() / kh
    if (site / "kokoro_onnx").is_dir():
        return site
    return None


def _add_engine_to_path() -> None:
    site = _engine_site()
    if site is None:
        return
    path = str(site)
    if path not in sys.path:
        sys.path.insert(0, path)


def kokoro_available() -> bool:
    """True when kokoro_onnx + onnxruntime can be imported right now."""
    if _engine_site() is not None:
        return True
    try:
        importlib.import_module("kokoro_onnx")  # noqa: F401
        importlib.import_module("onnxruntime")  # noqa: F401
        return True
    except Exception:
        return False


def ensure_kokoro_engine(on_log: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Make the Kokoro packages usable — downloads the tier once."""
    def _log(line: str) -> None:
        if on_log is not None:
            try:
                on_log(line)
            except Exception:
                pass

    if kokoro_available():
        _add_engine_to_path()
        return {"ok": True, "downloaded": False, "message": "kokoro engine ready"}

    descriptor = _runtime_descriptor()
    asset = descriptor.get("kokoro_asset")
    release_url = descriptor.get("release_url")
    kh = descriptor.get("kokoro_hash")
    if not (isinstance(asset, str) and asset and isinstance(release_url, str) and release_url):
        _log("the Kokoro engine is not available in this build")
        return {"ok": False, "downloaded": False, "message": "the Kokoro engine is not part of this build"}

    target = kokoro_engine_root() / str(kh)
    marker = target / ".ready"
    if not marker.is_file():
        url = f"{release_url.rstrip('/')}/{asset}"
        _log(f"downloading the Kokoro engine ({asset})…")
        try:
            _download_and_extract(url, target, _log)
        except Exception as e:
            _log(f"Kokoro engine download failed: {e}")
            return {"ok": False, "downloaded": False, "message": f"download failed: {e}"}
        try:
            marker.write_text("ok", encoding="utf-8")
        except OSError:
            pass
    _add_engine_to_path()
    if not kokoro_available():
        return {
            "ok": False,
            "downloaded": False,
            "message": "the Kokoro engine was extracted but kokoro_onnx is still missing",
        }
    _log("Kokoro engine ready")
    return {"ok": True, "downloaded": True, "message": "Kokoro engine downloaded"}


def _download_and_extract(url: str, target: Path, on_log: Optional[Callable[[str], None]] = None) -> None:
    import urllib.request
    import zipfile

    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.parent / f".staging-{target.name}-{os.getpid()}"
    try:
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True, exist_ok=True)
        archive = staging / "asset.zip"
        req = urllib.request.Request(url, headers={"User-Agent": "speak-epub/1 (kokoro engine)"})
        with urllib.request.urlopen(req, timeout=_DL_TIMEOUT_SEC) as resp:
            with open(archive, "wb") as f:
                while True:
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(staging)
        archive.unlink(missing_ok=True)
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        shutil.move(str(staging), str(target))
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def kokoro_model_paths() -> tuple[Path, Path]:
    root = kokoro_models_root()
    return root / MODEL_FILE, root / VOICES_FILE


def validate_kokoro_voice(voice: Any) -> str:
    """Return a valid Kokoro voice id or raise ValueError."""
    if not isinstance(voice, str):
        raise ValueError(f"unknown Kokoro voice {voice!r}")
    wanted = voice.strip()
    if not wanted:
        raise ValueError("Kokoro voice must be non-empty")
    if wanted in KOKORO_VOICES:
        return wanted
    # accept any id present in the downloaded voice pack (the catalogue is
    # broader than the curated shortlist)
    model, voices = kokoro_model_paths()
    if voices.is_file():
        try:
            import numpy as np

            data = np.load(str(voices))
            if wanted in set(data.files):
                return wanted
        except Exception:
            pass
    raise ValueError(
        f"unknown Kokoro voice {wanted!r} (choose one of: {', '.join(KOKORO_VOICES)})"
    )


def kokoro_model_ready() -> bool:
    """True when both weight files are present and plausible."""
    model, voices = kokoro_model_paths()
    try:
        return (
            model.is_file()
            and voices.is_file()
            and model.stat().st_size > 50_000_000
            and voices.stat().st_size > 1_000_000
        )
    except OSError:
        return False


def kokoro_ready(voice: Any) -> bool:
    """True when the engine can synthesize this voice right now."""
    if not isinstance(voice, str) or not voice.strip():
        return False
    if not kokoro_model_ready():
        return False
    try:
        validate_kokoro_voice(voice)
    except ValueError:
        return False
    return kokoro_available()


def _download_file(url: str, dest: Path, label: str, log_fn: Callable[[str], None]) -> None:
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "speak-epub/1.0"})
    started = time.monotonic()
    done = 0
    total: Optional[int] = None
    next_mark = _DL_PROGRESS_EVERY
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with urllib.request.urlopen(req, timeout=_DL_TIMEOUT_SEC) as resp:
            try:
                length = resp.headers.get("Content-Length")
                total = int(length) if length else None
            except Exception:
                total = None
            with open(tmp, "wb") as f:
                while True:
                    if time.monotonic() - started > _DL_TOTAL_TIMEOUT_SEC:
                        raise RuntimeError(f"download timed out after {_DL_TOTAL_TIMEOUT_SEC}s for {label}")
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if done >= next_mark:
                        next_mark = done + _DL_PROGRESS_EVERY
                        tail = f" of ~{total // (1024 * 1024)} MB" if total else ""
                        log_fn(f"downloading {label}: {done // (1024 * 1024)} MB{tail}…")
    except Exception as e:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"download failed for {label}: {e}") from e
    if done <= 0:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"download failed for {label}: empty response")
    if total is not None and done < total:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"download failed for {label}: incomplete body ({done} of {total} bytes)")
    os.replace(tmp, dest)


def download_kokoro_model(on_log: Optional[Callable[[str], None]] = None, force: bool = False) -> Dict[str, Any]:
    """Download the model + voice pack into the models directory."""
    def _log(msg: str) -> None:
        if on_log:
            try:
                on_log(msg)
            except Exception:
                pass

    root = kokoro_models_root()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise RuntimeError(f"cannot create the Kokoro models directory {root}: {e}") from e

    # The model files and the engine packages are two separate downloads, and
    # a model without the engine cannot synthesize anything. Downloading the
    # model used to stop here when the weights were present, so a machine
    # missing only the engine tier reported "already downloaded" forever and
    # every build failed with "download the model first".
    engine_result = ensure_kokoro_engine(on_log=_log)
    if not engine_result.get("ok"):
        raise RuntimeError(str(engine_result.get("message") or "the Kokoro engine is unavailable"))
    engine_downloaded = bool(engine_result.get("downloaded"))

    model, voices = kokoro_model_paths()
    model_downloaded = False
    if kokoro_model_ready() and not force:
        _log("Kokoro model already downloaded")
    else:
        model_downloaded = True
        _log("downloading the Kokoro model (~310 MB)…")
        _download_file(_MODEL_URL, model, "kokoro-v1.0.onnx", _log)
        _log("downloading the Kokoro voice pack (~27 MB)…")
        _download_file(_VOICES_URL, voices, "voices-v1.0.bin", _log)
        if not kokoro_model_ready():
            raise RuntimeError("Kokoro download finished but the files are incomplete")
        _log("Kokoro model downloaded")
    return {
        "model": str(model),
        "voices": str(voices),
        "bytes": (model.stat().st_size if model.is_file() else 0)
        + (voices.stat().st_size if voices.is_file() else 0),
        # what actually happened, so the UI stops claiming a download that
        # did not happen (or hiding one that did)
        "engineDownloaded": engine_downloaded,
        "modelDownloaded": model_downloaded,
    }


def list_kokoro_voices() -> Dict[str, Any]:
    """Status payload for the Settings UI."""
    root = kokoro_models_root()
    model_ok = kokoro_model_ready()
    engine_ok = kokoro_available()
    ready = bool(model_ok and engine_ok)
    voices = []
    for vid, meta in KOKORO_VOICES.items():
        voices.append(
            {
                "id": vid,
                "lang": meta["lang"],
                "gender": meta["gender"],
                "accent": meta["accent"],
                "note": meta.get("note", ""),
                # `downloaded` is the literal state of the model FILES; `ready`
                # is whether the engine can actually speak. Conflating the two
                # made a machine with the weights but no engine look "not
                # downloaded" while the download button refused to act.
                "downloaded": model_ok,
                "ready": ready,
            }
        )
    return {
        "modelsDir": str(root),
        "default": DEFAULT_KOKORO_VOICE,
        "voices": voices,
        "engineAvailable": engine_ok,
        "modelReady": model_ok,
        "ready": ready,
    }


def rate_to_speed(rate: Any) -> float:
    """Edge-style rate ('+25%') → Kokoro speed, clamped 0.75–2.0 like Piper."""
    try:
        num = int(normalize_tts_rate(rate).rstrip("%"))
    except Exception:
        num = 0
    num = max(-100, min(100, num))
    return max(0.75, min(2.0, 1.0 + num / 100.0))


def effective_kokoro_parallel() -> int:
    """Worker count for Kokoro: CPU-bound ONNX, clamped 1..4."""
    try:
        cores = os.cpu_count() or 4
    except Exception:
        cores = 4
    return max(1, min(int(cores) // 2, 4))


def _load_kokoro():
    with _CACHE_LOCK:
        cached = _CACHE.get("instance")
        if cached is not None:
            return cached
        _add_engine_to_path()
        from kokoro_onnx import Kokoro

        model, voices = kokoro_model_paths()
        if not (model.is_file() and voices.is_file()):
            raise RuntimeError(
                "the Kokoro model is not downloaded — download it in Settings first"
            )
        instance = Kokoro(str(model), str(voices))
        _CACHE["instance"] = instance
        return instance


def _unavailable_message(voice: str) -> str:
    if not kokoro_model_ready():
        return "the Kokoro model is not downloaded (download it in Settings first)"
    if not kokoro_available():
        return "the Kokoro engine is not installed in this build — install it or use another engine"
    return f"Kokoro voice {voice} is unavailable"


def tts_text_to_mp3_kokoro(
    text: str,
    output_path: str,
    voice: str,
    retries: int = 5,
    rate: Optional[str] = None,
    ffmpeg_bin: str = "ffmpeg",
    on_retry: Optional[Callable[[int, Exception], None]] = None,
) -> None:
    """Synthesize `text` fully offline into an MP3 part (48k mono, like Edge)."""
    name = validate_kokoro_voice(voice)
    if not kokoro_model_ready():
        raise RuntimeError(_unavailable_message(name))
    if not kokoro_available():
        result = ensure_kokoro_engine()
        if not result.get("ok"):
            raise RuntimeError(
                "the Kokoro engine is not installed in this build — "
                "use another engine or install the components"
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
        raise RuntimeError(f"cannot create the output directory {output.parent}: {e}") from e

    ffmpeg = shutil.which(ffmpeg_bin)
    if not ffmpeg:
        from core.ffmpeg_setup import ensure_ffmpeg

        try:
            ensure_ffmpeg()
        except Exception:
            pass
        ffmpeg = shutil.which(ffmpeg_bin)
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found on PATH — required for Kokoro MP3 encoding")

    meta = KOKORO_VOICES.get(name, {})
    lang = str(meta.get("lang") or ("en-gb" if name.startswith("b") else "en-us"))
    speed = rate_to_speed(rate)
    wav_path = output.with_suffix(".part.wav")

    last: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            engine = _load_kokoro()
            samples, sr = engine.create(text, voice=name, speed=speed, lang=lang)
            with wave.open(str(wav_path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sr)
                wf.writeframes((samples * 32767).astype("int16").tobytes())

            proc = subprocess.run(
                [
                    ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                    "-i", str(wav_path),
                    "-codec:a", "libmp3lame", "-b:a", "48k", "-ac", "1", "-ar", "24000",
                    str(output),
                ],
                capture_output=True,
                timeout=900,
            )
            if proc.returncode != 0 or not output.is_file():
                stderr = (proc.stderr or b"").decode("utf-8", "replace")[-400:]
                output.unlink(missing_ok=True)
                raise RuntimeError(f"ffmpeg failed to encode Kokoro output: {stderr}")

            ok, reason = verify_part_audio(str(output), text, rate=rate)
            if ok:
                return
            output.unlink(missing_ok=True)
            raise RuntimeError(f"Kokoro produced invalid audio ({reason}) for {output.name}")
        except Exception as e:
            last = e
            try:
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
            raise RuntimeError(
                f"Kokoro TTS failed after {retries} attempts for {output.name}: {e}"
            ) from e
        finally:
            try:
                wav_path.unlink(missing_ok=True)
            except Exception:
                pass
    if last is not None:
        raise RuntimeError(f"Kokoro TTS failed for {output.name}: {last}")
