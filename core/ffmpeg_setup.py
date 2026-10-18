"""Auto-repair a missing FFmpeg/ffprobe installation.

ffmpeg/ffprobe power local-TTS MP3 encoding, chapter merging, M4B/M4A
packaging, truncation auto-repair and audio post-processing. Rather than
failing with "ffmpeg not found on PATH", ensure_ffmpeg() self-heals:

1. ffmpeg already on PATH -> done.
2. a previously installed portable build -> prepend to PATH -> done.
3. neither: download a static build (gyan.dev on Windows, BtbN/Linux and
   evermeet/macOS — all built from official sources) into a per-user
   directory, verify it runs, and prepend it to PATH for this process.

The install lives outside admin-protected locations (LOCALAPPDATA /
per-user data dir), is shared by the CLI and the GUI, and survives app
updates. Set SPEAK_EPUB_FFMPEG_DIR to relocate it (tests override this).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Iterable, Optional

#: Only consulted after a failed auto-install, so a user retrying offline
#: keeps concrete options instead of a dead end.
MANUAL_HELP = "https://github.com/BtbN/FFmpeg-Builds/releases/latest"

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
    req = urllib.request.Request(
        url, headers={"User-Agent": "speak-epub/1 (ffmpeg auto-install)"}
    )
    with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as f:
        total = _content_length(resp.headers)
        got = 0
        last_report = 0
        while True:
            chunk = resp.read(_DL_CHUNK)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            if total and got - last_report >= _DL_REPORT_EVERY:
                _log(on_log, f"  downloading ffprobe/ffmpeg archive... {int(got * 100 / max(total, 1))}%")
                last_report = got


def _extract_targets(archive: Path, out_bin: Path) -> None:
    """Pull ffmpeg/ffprobe from wherever they sit inside the archive.

    Archives nest bin/ a level or two deep (ffmpeg-7.1-.../bin/) or ship a
    flat single file (evermeet zips); basename matching covers both. Single
    output dir, capped member sizes, names only (no traversal), symlinks skipped.
    """
    targets = {"ffmpeg.exe", "ffprobe.exe", "ffmpeg", "ffprobe"}
    out_bin.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                if Path(info.filename).name.lower() in targets and info.file_size <= _MAX_BINARY_BYTES:
                    with zf.open(info) as src, open(out_bin / Path(info.filename).name, "wb") as dst:
                        shutil.copyfileobj(src, dst)
    elif tarfile.is_tarfile(str(archive)):
        with tarfile.open(str(archive)) as tf:
            for member in tf:
                if not (member.isfile() and Path(member.name).name.lower() in targets and member.size <= _MAX_BINARY_BYTES):
                    continue
                src = tf.extractfile(member)
                if src is None:
                    continue
                with src, open(out_bin / Path(member.name).name, "wb") as dst:
                    shutil.copyfileobj(src, dst)
    if os.name != "nt":
        for exe in out_bin.iterdir():
            try:
                exe.chmod(0o755)
            except OSError:
                pass


def _install_from_zips(urls: Iterable[str], on_log: Optional[Callable[[str], None]]) -> bool:
    """Try URL candidates until a verified ffmpeg+ffprobe pair is in place."""
    out_bin = bin_dir()
    for url in urls:
        with tempfile.TemporaryDirectory(prefix="speak-epub-ffmpeg-") as td:
            archive = Path(td) / Path(url.split("?")[0]).name
            try:
                _download(url, archive, on_log)
                _extract_targets(archive, out_bin)
            except (urllib.error.URLError, urllib.error.HTTPError, OSError, zipfile.BadZipFile, tarfile.TarError) as e:
                from urllib.parse import urlparse

                _log(
                    on_log,
                    f"  source unreachable ({urlparse(url).netloc}: "
                    f"{e.__class__.__name__}) — trying the next mirror...",
                )
                continue
            exe = out_bin / _exe_name("ffmpeg")
            if exe.is_file() and _verify_binary(str(exe)):
                _prepend_to_path(out_bin)
                _log(on_log, f"FFmpeg installed: {out_bin}")
                if not (out_bin / _exe_name("ffprobe")).is_file():
                    _log(on_log, "Warning: ffprobe missing in the portable build — duration probing disabled.")
                return True
    return False


def ensure_ffmpeg(on_log: Optional[Callable[[str], None]] = None) -> bool:
    """True when ffmpeg is runnable afterwards (was found, installed or repaired).

    Safe to call any number of times: on PATH change nothing; installed dir
    reuse is instant; a cold user pays one download (~20-120 MB by platform).
    """
    if shutil.which("ffmpeg") is not None:
        return True
    preinstalled = bin_dir() / _exe_name("ffmpeg")
    if preinstalled.is_file():
        _prepend_to_path(bin_dir())
        if shutil.which("ffmpeg") is not None:
            return True
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
    _log(on_log, f"Warning: FFmpeg auto-install failed — install it manually (see {MANUAL_HELP}).")
    return shutil.which("ffmpeg") is not None
