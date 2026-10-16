"""Local offline TTS via Piper (CPU, no network) — optional engine next to Edge TTS.

Voice models (.onnx + .onnx.json, ~63–115 MB each) live under
``<user>/Documents/speak-epub/models/piper`` (override: SPEAK_EPUB_MODELS_DIR)
and are downloaded on demand from the official rhasspy/piper-voices repo.

Design notes:
- heavy deps (piper / onnxruntime) are imported lazily so Edge-only runs and
  app startup never pay for them
- synthesis happens fully offline; part MP3s are encoded with ffmpeg at the
  same 32k mono profile as Edge output, so resume/verify/merge stay identical
- ``rate`` keeps its Edge meaning ("+25%" = 1.25x speed) and maps onto Piper's
  ``length_scale``; the effective speed is clamped to 0.75–2.0 so the existing
  duration-based verification keeps a safe margin
"""
import os
import shutil
import subprocess
import threading
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

_VOICE_CACHE: Dict[str, Any] = {}
_VOICE_LOCK = threading.Lock()


def local_models_root() -> Path:
    """Directory holding downloaded Piper voices (env override for tests)."""
    env = os.environ.get("SPEAK_EPUB_MODELS_DIR")
    if env:
        return Path(env)
    from core.tts import user_output_base

    return user_output_base() / "models" / "piper"


def _piper_available() -> bool:
    try:
        import importlib.util

        return importlib.util.find_spec("piper") is not None
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
    except OSError:
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


def download_local_voice(voice: Any, on_log: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Download a curated voice into the models dir; returns its status dict."""

    def _log(msg: str) -> None:
        if on_log:
            try:
                on_log(msg)
            except Exception:
                pass

    name = validate_local_voice(voice)
    if not _piper_available():
        raise RuntimeError("piper-tts is not installed — local voices unavailable in this build")
    from piper.download_voices import download_voice

    root = local_models_root()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise RuntimeError(f"cannot create models directory {root}: {e}") from e

    size_mb = LOCAL_VOICES[name]["size_mb"]
    if local_voice_ready(name):
        _log(f"local voice {name} already downloaded")
    else:
        _log(f"downloading local voice {name} (~{size_mb} MB)...")
        try:
            download_voice(name, root)
        except Exception as e:
            raise RuntimeError(f"failed to download local voice {name}: {e}") from e
        if not local_voice_ready(name):
            raise RuntimeError(f"download finished but model files are incomplete for {name}")
        _log(f"local voice {name} downloaded")
    onnx, _ = local_voice_paths(name)
    return {
        "id": name,
        "modelsDir": str(root),
        "path": str(onnx),
        "bytes": onnx.stat().st_size,
    }


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
        if not local_voice_ready(voice):
            raise ValueError(f"local voice not downloaded: {voice} (download it in Settings first)")
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
    """Edge-style rate ('+25%') → Piper length_scale (1/1.25), speed clamped 0.75–2.0."""
    normalized = normalize_tts_rate(rate)
    try:
        num = int(normalized.rstrip("%"))
    except Exception:
        num = 0
    num = max(-25, min(100, num))
    speed = max(0.75, min(2.0, 1.0 + num / 100.0))
    return 1.0 / speed


def _load_voice(voice: str):
    with _VOICE_LOCK:
        cached = _VOICE_CACHE.get(voice)
        if cached is not None:
            return cached
        onnx, _ = local_voice_paths(voice)
        from piper import PiperVoice

        loaded = PiperVoice.load(str(onnx))
        _VOICE_CACHE[voice] = loaded
        return loaded


def tts_text_to_mp3_local(
    text: str,
    output_path: str,
    voice: str,
    retries: int = 5,
    rate: Optional[str] = None,
    ffmpeg_bin: str = "ffmpeg",
) -> None:
    """Synthesize `text` fully offline into an MP3 part (32k mono, like Edge).

    Synchronous like the Piper API itself; deterministic CPU work, so the
    `retries` parameter is accepted for signature parity but not used.
    """
    name = validate_local_voice(voice)
    if not local_voice_ready(name):
        raise RuntimeError(f"local voice not downloaded: {name} (download it in Settings first)")

    output = Path(output_path)
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    wav_path = output.with_suffix(".part.wav")

    try:
        from piper import SynthesisConfig

        piper_voice = _load_voice(name)
        syn_config = SynthesisConfig(length_scale=rate_to_length_scale(rate))
        with wave.open(str(wav_path), "wb") as wf:
            piper_voice.synthesize_wav(text, wf, syn_config=syn_config)

        ffmpeg = shutil.which(ffmpeg_bin)
        if not ffmpeg:
            raise RuntimeError("ffmpeg not found on PATH — required for local TTS MP3 encoding")
        proc = subprocess.run(
            [
                ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(wav_path),
                "-codec:a", "libmp3lame", "-b:a", "32k", "-ac", "1",
                str(output),
            ],
            capture_output=True,
            timeout=600,
        )
        if proc.returncode != 0 or not output.is_file():
            stderr = (proc.stderr or b"").decode("utf-8", "replace")[-400:]
            raise RuntimeError(f"ffmpeg failed to encode local TTS output: {stderr}")
    finally:
        try:
            wav_path.unlink(missing_ok=True)
        except Exception:
            pass

    ok, reason = verify_part_audio(str(output), text)
    if not ok:
        try:
            output.unlink(missing_ok=True)
        except Exception:
            pass
        raise RuntimeError(f"local TTS produced invalid audio ({reason}) for {output.name}")
