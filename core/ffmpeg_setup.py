"""Auto-repair a missing FFmpeg/ffprobe installation.

ffmpeg/ffprobe power local-TTS MP3 encoding, chapter merging, M4B/M4A
packaging, truncation auto-repair and audio post-processing. Rather than
failing with "ffmpeg not found on PATH", ensure_ffmpeg() self-heals:

1. ffmpeg already on PATH -> done.
2. a previously installed portable build -> verify it runs, prepend to PATH.
3. neither: download a static build (gyan.dev on Windows, BtbN/Linux and
   evermeet/macOS — all built from official sources) into a per-user
   directory, verify it runs, and prepend it to PATH for this process.

The install lives outside admin-protected locations (LOCALAPPDATA /
per-user data dir), is shared by the CLI and the GUI, and survives app
updates. Set SPEAK_EPUB_FFMPEG_DIR to relocate it (tests override this).
"""

from __future__ import annotations

import http.client
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Iterable, Optional

#: Only consulted after a failed auto-install, so a user retrying offline
#: keeps concrete options instead of a dead end.
MANUAL_HELP = {
    "nt": "https://www.gyan.dev/ffmpeg/builds/",
    "darwin": "https://evermeet.cx/ffmpeg/",
    "linux": "https://github.com/BtbN/FFmpeg-Builds/releases/latest",
}

_WINDOWS_ZIPS = (
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
    "https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/"
    "ffmpeg-master-latest-win64-gpl.zip",
)
_LINUX_ZIPS = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/"
    "ffmpeg-master-latest-linux64-gpl.tar.xz",
)
_MAC_ZIPS = (
    "https://evermeet.cx/ffmpeg/getrelease/zip",
    "https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip",
)

_DL_CHUNK = 1024 * 256
_DL_REPORT_EVERY = 10 * 1024 * 1024
_MAX_BINARY_BYTES = 150 * 1024 * 1024
#: Overall budget for one archive download (a trickling mirror must not
#: stall the install forever — the old code only had a per-socket timeout).
_DOWNLOAD_DEADLINE_SEC = 900
#: Cap for the transferred archive itself.
_MAX_ARCHIVE_BYTES = 400 * 1024 * 1024
#: Name of the on-disk lock that serializes concurrent installs.
_INSTALL_LOCK_NAME = ".install.lock"

#: Guards the process-wide PATH mutation and the install directory inside
#: this process (the CLI and the sidecar may both call ensure_ffmpeg).
_INSTALL_LOCK = threading.Lock()


def _log(on_log: Optional[Callable[[str], None]], line: str) -> None:
    if on_log:
        try:
            on_log(line)
        except Exception:
            pass


def install_root() -> Path:
    override = os.environ.get("SPEAK_EPUB_FFMPEG_DIR")
    if override:
        return Path(override)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / "speak-epub" / "ffmpeg"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "speak-epub" / "ffmpeg"
    return Path.home() / ".local" / "share" / "speak-epub" / "ffmpeg"


def bin_dir() -> Path:
    return install_root() / "bin"


def _exe_name(base: str) -> str:
    return base + (".exe" if os.name == "nt" else "")


def _prepend_to_path(d: Path) -> None:
    s = str(d)
    current = os.environ.get("PATH", "")
    if s in current.split(os.pathsep):
        return
    os.environ["PATH"] = s + os.pathsep + current


def _verify_binary(exe: str) -> bool:
    """`ffmpeg -version` must exit 0 — a corrupt download must not pass."""
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    try:
        proc = subprocess.run(
            [exe, "-hide_banner", "-version"],
            capture_output=True,
            timeout=60,
            **kwargs,
        )
    except Exception:
        return False
    return proc.returncode == 0


def _content_length(headers) -> int:
    try:
        return int(headers.get("Content-Length") or 0)
    except Exception:
        return 0


def _download(url: str, dest: Path, on_log: Optional[Callable[[str], None]]) -> None:
    """Fetch one archive with an overall deadline and a size cap.

    The per-socket timeout alone was not enough: a mirror that trickles one
    byte per minute kept the install (and the GUI) hanging indefinitely.
    """
    req = urllib.request.Request(
        url, headers={"User-Agent": "speak-epub/1 (ffmpeg auto-install)"}
    )
    started = time.monotonic()
    with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as f:
        total = _content_length(resp.headers)
        got = 0
        last_report = 0
        while True:
            if time.monotonic() - started > _DOWNLOAD_DEADLINE_SEC:
                raise TimeoutError(f"download exceeded {_DOWNLOAD_DEADLINE_SEC}s")
            chunk = resp.read(_DL_CHUNK)
            if not chunk:
                break
            got += len(chunk)
            if got > _MAX_ARCHIVE_BYTES:
                raise OSError(f"archive exceeds the size cap ({_MAX_ARCHIVE_BYTES} bytes)")
            f.write(chunk)
            if total and got - last_report >= _DL_REPORT_EVERY:
                _log(on_log, f"  downloading ffprobe/ffmpeg archive... {int(got * 100 / max(total, 1))}%")
                last_report = got
    if total and got < total:
        raise OSError(f"incomplete download ({got} of {total} bytes)")


def _extract_targets(archive: Path, out_bin: Path) -> int:
    """Pull ffmpeg/ffprobe from wherever they sit inside the archive.

    Archives nest bin/ a level or two deep (ffmpeg-7.1-.../bin/) or ship a
    flat single file (evermeet zips); basename matching covers both. Single
    output dir, capped member sizes, names only (no traversal), symlinks skipped.

    Returns the number of extracted binaries (0 = the archive did not contain
    any — a "mirror unreachable" message would be misleading then).
    """
    targets = {"ffmpeg.exe", "ffprobe.exe", "ffmpeg", "ffprobe"}
    out_bin.mkdir(parents=True, exist_ok=True)
    found = 0
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                if Path(info.filename).name.lower() in targets and info.file_size <= _MAX_BINARY_BYTES:
                    with zf.open(info) as src, open(out_bin / Path(info.filename).name, "wb") as dst:
                        shutil.copyfileobj(src, dst, length=_MAX_BINARY_BYTES)
                    found += 1
    elif tarfile.is_tarfile(str(archive)):
        with tarfile.open(str(archive)) as tf:
            for member in tf:
                if not (member.isfile() and Path(member.name).name.lower() in targets and member.size <= _MAX_BINARY_BYTES):
                    continue
                src = tf.extractfile(member)
                if src is None:
                    continue
                with src, open(out_bin / Path(member.name).name, "wb") as dst:
                    shutil.copyfileobj(dst=dst, src=src, length=_MAX_BINARY_BYTES)
                found += 1
    else:
        return 0
    if os.name != "nt":
        for exe in out_bin.iterdir():
            try:
                exe.chmod(0o755)
            except OSError:
                pass
    return found


def _install_from_zips(urls: Iterable[str], on_log: Optional[Callable[[str], None]]) -> bool:
    """Try URL candidates until a verified ffmpeg+ffprobe pair is in place."""
    out_bin = bin_dir()
    for url in urls:
        with tempfile.TemporaryDirectory(prefix="speak-epub-ffmpeg-") as td:
            archive = Path(td) / Path(url.split("?")[0]).name
            # stage the extraction: a half-written binary must never end up
            # in the live bin/ directory (a later run would adopt it)
            staging = Path(td) / "bin"
            try:
                _download(url, archive, on_log)
                extracted = _extract_targets(archive, staging)
                if not extracted:
                    _log(on_log, "  the archive contained no ffmpeg/ffprobe — trying the next mirror...")
                    continue
                exe = staging / _exe_name("ffmpeg")
                probe = staging / _exe_name("ffprobe")
                if not (exe.is_file() and _verify_binary(str(exe))):
                    _log(on_log, "  the downloaded ffmpeg does not run — trying the next mirror...")
                    continue
                if not (probe.is_file() and _verify_binary(str(probe))):
                    # ffprobe is not optional: without it the chapter markers
                    # and the truncation gate are silently disabled
                    _log(on_log, "  the archive has no working ffprobe — trying the next mirror...")
                    continue
                out_bin.mkdir(parents=True, exist_ok=True)
                for name in (_exe_name("ffmpeg"), _exe_name("ffprobe")):
                    src = staging / name
                    if src.is_file():
                        shutil.copy2(src, out_bin / name)
                _prepend_to_path(out_bin)
                _log(on_log, f"FFmpeg installed: {out_bin}")
                return True
            except (
                urllib.error.URLError,
                urllib.error.HTTPError,
                http.client.HTTPException,
                OSError,
                TimeoutError,
                zipfile.BadZipFile,
                tarfile.TarError,
            ) as e:
                from urllib.parse import urlparse

                _log(
                    on_log,
                    f"  source unreachable ({urlparse(url).netloc}: "
                    f"{e.__class__.__name__}) — trying the next mirror...",
                )
                continue
    return False


def ensure_ffmpeg(on_log: Optional[Callable[[str], None]] = None) -> bool:
    """True when ffmpeg is runnable afterwards (was found, installed or repaired).

    Safe to call any number of times: on PATH change nothing; installed dir
    reuse is instant; a cold user pays one download (~20-120 MB by platform).
    """
    if shutil.which("ffmpeg") is not None:
        return True
    with _INSTALL_LOCK:
        if shutil.which("ffmpeg") is not None:
            return True
        preinstalled = bin_dir() / _exe_name("ffmpeg")
        if preinstalled.is_file():
            # an existing install is only adopted when it actually RUNS: a
            # half-extracted binary used to be adopted and then broke every
            # later ffmpeg call
            if _verify_binary(str(preinstalled)):
                _prepend_to_path(bin_dir())
                if shutil.which("ffmpeg") is not None:
                    return True
            else:
                _log(on_log, "The existing FFmpeg install does not run — reinstalling.")
        urls = (
            _WINDOWS_ZIPS if os.name == "nt"
            else _LINUX_ZIPS if sys.platform == "linux"
            else _MAC_ZIPS
        )
        _log(
            on_log,
            "FFmpeg not found on PATH — downloading the portable build automatically "
            "(one-time, ~a minute)...",
        )
        try:
            os.makedirs(install_root(), exist_ok=True)
        except OSError as e:
            _log(on_log, f"Warning: cannot create the ffmpeg install dir ({e}).")
            return False
        if _install_from_zips(urls, on_log):
            return True
        _help = MANUAL_HELP.get("darwin" if sys.platform == "darwin" else ("nt" if os.name == "nt" else "linux"))
        _log(on_log, f"Warning: FFmpeg auto-install failed — install it manually (see {_help}).")
        if sys.platform == "darwin":
            _log(
                on_log,
                "macOS note: the portable build is unsigned — allow it in System Settings > Privacy & Security.",
            )
        return shutil.which("ffmpeg") is not None
