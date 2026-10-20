"""Self-contained runtime for the CLI.

The desktop app downloads its Python runtime tier once and caches it in the
user profile. The CLI does the same: when the backend dependencies are
missing, it fetches the very same release asset
(`speak-epub-runtime-<hash>.zip` — the cache key is derived from the
interpreter build and `requirements.txt`, so both share one download) and
re-runs itself with that interpreter.

Only the standard library is used here — this module runs BEFORE the
backend dependencies are imported.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Optional

#: The modules the CLI needs to do its job.
REQUIRED_MODULES = ("ebooklib", "bs4", "edge_tts", "lxml", "requests")

#: Progress is reported every this many bytes.
_PROGRESS_EVERY = 10 * 1024 * 1024

#: Socket timeout (s) for the runtime download.
_TIMEOUT_SEC = 30

#: Overall deadline (s) for the runtime download.
_TOTAL_TIMEOUT_SEC = 900


def descriptor_path() -> Optional[Path]:
    """Find `runtime.json` (shipped next to the CLI package)."""
    bases = [Path(__file__).resolve().parent.parent, Path.cwd()]
    for base in bases:
        candidate = base / "runtime.json"
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def read_descriptor() -> dict:
    """The runtime descriptor (empty dict when there is none)."""
    path = descriptor_path()
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def backend_available() -> bool:
    """True when the current interpreter has the backend dependencies."""
    import importlib.util

    for name in REQUIRED_MODULES:
        try:
            if importlib.util.find_spec(name) is None:
                return False
        except Exception:
            return False
    return True


def cache_root() -> Path:
    """Where the runtime tier is cached (per user, never in the app dir)."""
    override = os.environ.get("SPEAK_EPUB_RUNTIME_DIR")
    if override:
        return Path(override)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / "speak-epub" / "runtime"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "speak-epub" / "runtime"
    return Path.home() / ".local" / "share" / "speak-epub" / "runtime"


def interpreter_in(runtime_dir: Path) -> Path:
    """The interpreter inside an unpacked runtime."""
    if os.name == "nt":
        return runtime_dir / "python" / "python.exe"
    return runtime_dir / "python" / "bin" / "python3"


def cached_interpreter(descriptor: dict) -> Optional[Path]:
    """The cached interpreter for this descriptor, when it is there."""
    runtime_hash = descriptor.get("hash")
    if not isinstance(runtime_hash, str) or not runtime_hash:
        return None
    python = interpreter_in(cache_root() / runtime_hash)
    return python if python.is_file() else None


def asset_url(descriptor: dict) -> Optional[str]:
    """The release URL of the runtime asset."""
    base = descriptor.get("release_url")
    asset = descriptor.get("asset")
    if not isinstance(base, str) or not isinstance(asset, str) or not base or not asset:
        return None
    return f"{base.rstrip('/')}/{asset}"


def _is_release_url(url: str) -> bool:
    """Only release URLs (github.com) may be downloaded."""
    try:
        from urllib.parse import urlparse

        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").lower()
    return host == "github.com" or host.endswith(".github.com")


def download_runtime(
    descriptor: dict,
    on_log: Optional[Callable[[str], None]] = None,
) -> Optional[Path]:
    """Download and unpack the runtime tier; returns the interpreter path."""
    def _log(line: str) -> None:
        if on_log is not None:
            try:
                on_log(line)
            except Exception:
                pass

    url = asset_url(descriptor)
    runtime_hash = descriptor.get("hash")
    if not url or not isinstance(runtime_hash, str) or not runtime_hash:
        _log("no runtime descriptor — cannot prepare the Python runtime")
        return None
    if not _is_release_url(url):
        _log(f"refusing a non-release runtime URL: {url}")
        return None

    root = cache_root()
    target = root / runtime_hash
    python = interpreter_in(target)
    if python.is_file():
        return python

    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        _log(f"cannot create the runtime cache dir: {e}")
        return None

    staging = root / f".staging-{runtime_hash}-{os.getpid()}"
    shutil.rmtree(staging, ignore_errors=True)
    try:
        staging.mkdir(parents=True, exist_ok=True)
        archive = staging / "runtime.zip"
        started = time.monotonic()
        req = urllib.request.Request(
            url, headers={"User-Agent": "speak-epub/1 (runtime bootstrap)"}
        )
        _log(f"downloading the Python runtime ({Path(url).name})…")
        total = 0
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SEC) as resp:
            try:
                total = int(resp.headers.get("Content-Length") or 0)
            except (TypeError, ValueError):
                total = 0
            done = 0
            next_mark = _PROGRESS_EVERY
            with open(archive, "wb") as f:
                while True:
                    if time.monotonic() - started > _TOTAL_TIMEOUT_SEC:
                        raise RuntimeError("the runtime download timed out")
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if done >= next_mark:
                        next_mark = done + _PROGRESS_EVERY
                        tail = f" of ~{total // (1024 * 1024)} MB" if total else ""
                        _log(f"downloading the Python runtime: {done // (1024 * 1024)} MB{tail}…")
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(staging)
        try:
            archive.unlink()
        except OSError:
            pass
        if not interpreter_in(staging).is_file():
            _log("the downloaded runtime has no interpreter")
            shutil.rmtree(staging, ignore_errors=True)
            return None
        shutil.rmtree(target, ignore_errors=True)
        staging.rename(target)
    except Exception as e:  # noqa: BLE001
        _log(f"the runtime download failed: {e}")
        shutil.rmtree(staging, ignore_errors=True)
        return None
    _log("the Python runtime is ready")
    return interpreter_in(target)


def ensure_runtime(on_log: Optional[Callable[[str], None]] = None) -> Optional[Path]:
    """The interpreter to run the backend with (the current one if it fits)."""
    if backend_available():
        return Path(sys.executable)
    descriptor = read_descriptor()
    if not descriptor:
        return None
    cached = cached_interpreter(descriptor)
    if cached is not None:
        return cached
    return download_runtime(descriptor, on_log=on_log)


def relaunch_with_runtime(argv: Optional[list[str]] = None) -> bool:
    """Re-run this script with the runtime interpreter.

    Returns False when there is nothing to do (no descriptor, no runtime) —
    the caller then reports the missing dependency as before.
    """
    if backend_available():
        return False
    descriptor = read_descriptor()
    if not descriptor:
        return False
    python = ensure_runtime(on_log=lambda line: print(line, flush=True))
    if python is None:
        return False
    script = Path(__file__).resolve()
    args = [str(python), str(script)] + list(argv if argv is not None else sys.argv[1:])
    env = dict(os.environ)
    # the CLI package's own code wins over anything in the runtime
    env["PYTHONPATH"] = os.pathsep.join(
        [str(script.parent)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])
    )
    env["SPEAK_EPUB_RUNTIME_ACTIVE"] = "1"
    try:
        if os.name == "nt":
            code = subprocess.call(args, env=env)
            sys.exit(code)
        os.execve(str(python), args, env)  # type: ignore[attr-defined]
    except Exception as e:  # noqa: BLE001
        print(f"cannot start the Python runtime: {e}", file=sys.stderr)
        sys.exit(1)
    return True  # unreachable
