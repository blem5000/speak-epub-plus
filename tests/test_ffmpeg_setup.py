# ffmpeg auto-repair: ensure_ffmpeg must repair a missing install rather
# than leaving "ffmpeg not found on PATH" to fail synthesis. All network
# and binaries are faked; no test downloads anything.
import io
import os
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


class _FakeResp:
    headers = {}

    def __init__(self, buf: io.BytesIO):
        self._buf = buf

    def read(self, n=-1):
        return self._buf.read(n)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_ffmpeg_zip() -> io.BytesIO:
    """A zip shaped like gyan essentials: bin/ nested one level deep."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("ffmpeg-7.1-essentials_build/bin/ffmpeg.exe", b"fake-binary")
        zf.writestr("ffmpeg-7.1-essentials_build/bin/ffprobe.exe", b"fake-binary")
        zf.writestr("ffmpeg-7.1-essentials_build/doc/README.txt", b"ignored")
    buf.seek(0)
    return buf


def _fake_ok_open(req, timeout=None):
    return _FakeResp(_fake_ffmpeg_zip())


@pytest.fixture()
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SPEAK_EPUB_FFMPEG_DIR", str(tmp_path / "ffmpeg-root"))
    monkeypatch.setattr("core.ffmpeg_setup.shutil.which", lambda name: None)
    yield tmp_path


class TestPaths:
    def test_install_root_per_platform(self, isolated_env, monkeypatch):
        import core.ffmpeg_setup as fs

        monkeypatch.delenv("SPEAK_EPUB_FFMPEG_DIR")
        if os.name == "nt":
            root = fs.install_root()
            assert root.name == "ffmpeg" and root.parent.name == "speak-epub"
        elif sys.platform == "darwin":
            assert "Application Support" in str(fs.install_root())
        else:
            expected = Path.home() / ".local" / "share" / "speak-epub" / "ffmpeg"
            assert fs.install_root() == expected

    def test_bin_dir_under_root(self, isolated_env):
        import core.ffmpeg_setup as fs

        assert fs.bin_dir() == fs.install_root() / "bin"


class TestEnsureShortCircuits:
    def test_already_on_path(self, isolated_env, monkeypatch):
        import core.ffmpeg_setup as fs

        monkeypatch.setattr(fs.shutil, "which", lambda name: "C:/anywhere/ffmpeg")
        assert fs.ensure_ffmpeg() is True

    def test_installed_dir_reused(self, isolated_env):
        import core.ffmpeg_setup as fs

        bin_path = fs.bin_dir()
        bin_path.mkdir(parents=True)
        exe = bin_path / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        exe.write_bytes(b"x")

        def which(name):
            return str(exe) if name == "ffmpeg" and str(bin_path) in os.environ.get("PATH", "") else None

        with patch.object(fs.shutil, "which", side_effect=which):
            assert fs.ensure_ffmpeg() is True
        assert str(bin_path) in os.environ["PATH"].split(os.pathsep)


class TestEnsureDownloads:
    def test_download_extract_verify(self, isolated_env, monkeypatch):
        import core.ffmpeg_setup as fs

        seen_urls = []

        def fake_open(req, timeout=None):
            seen_urls.append(getattr(req, "full_url", req))
            return _fake_ok_open(req, timeout)

        monkeypatch.setattr(fs.urllib.request, "urlopen", fake_open)
        monkeypatch.setattr(fs.subprocess, "run", lambda args, **kw: SimpleNamespace(returncode=0))
        assert fs.ensure_ffmpeg() is True
        assert any("gyan.dev" in u for u in seen_urls)
        assert (fs.bin_dir() / "ffmpeg.exe").is_file()
        assert (fs.bin_dir() / "ffprobe.exe").is_file()
        assert str(fs.bin_dir()) in os.environ["PATH"].split(os.pathsep)

    def test_404_falls_back_to_btb_n(self, isolated_env, monkeypatch):
        import core.ffmpeg_setup as fs
        import urllib.error

        seen_urls = []

        def fake_open(req, timeout=None):
            url = getattr(req, "full_url", req)
            seen_urls.append(url)
            if len(seen_urls) == 1:
                raise urllib.error.HTTPError(url, 404, "not found", {}, io.BytesIO(b""))
            return _fake_ok_open(req, timeout)

        monkeypatch.setattr(fs.urllib.request, "urlopen", fake_open)
        monkeypatch.setattr(fs.subprocess, "run", lambda args, **kw: SimpleNamespace(returncode=0))
        assert fs.ensure_ffmpeg() is True
        assert len(seen_urls) == 2
        assert "BtbN" in seen_urls[1]

    def test_bad_archive_then_false(self, isolated_env, monkeypatch):
        import core.ffmpeg_setup as fs

        monkeypatch.setattr(fs.urllib.request, "urlopen", lambda req, timeout=None: _FakeResp(io.BytesIO(b"")))
        monkeypatch.setattr(fs.subprocess, "run", lambda args, **kw: SimpleNamespace(returncode=1))
        logs = []
        assert fs.ensure_ffmpeg(on_log=logs.append) is False
        assert any("manually" in line for line in logs)

    def test_only_ffprobe_archive_no_success(self, isolated_env, monkeypatch):
        """A partial archive (no ffmpeg) must not report success."""
        import core.ffmpeg_setup as fs

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("ffmpeg-7.1-essentials_build/bin/ffprobe.exe", b"probe")
        buf.seek(0)
        monkeypatch.setattr(fs.urllib.request, "urlopen", lambda req, timeout=None: _FakeResp(buf))
        monkeypatch.setattr(fs.subprocess, "run", lambda args, **kw: SimpleNamespace(returncode=0))
        assert fs.ensure_ffmpeg() is False
        assert (fs.bin_dir() / "ffprobe.exe").is_file()
        assert not (fs.bin_dir() / "ffmpeg.exe").is_file()


class TestNeverFocused:
    def test_unwritable_root_warns_false(self, isolated_env, monkeypatch):
        import core.ffmpeg_setup as fs

        blocked = isolated_env / "blocked"
        blocked.write_text("a file, not a dir")
        monkeypatch.setenv("SPEAK_EPUB_FFMPEG_DIR", str(blocked / "sub"))
        monkeypatch.setattr(fs.shutil, "which", lambda name: None)
        assert fs.ensure_ffmpeg() is False

    def test_mac_chain_shape(self, isolated_env):
        import core.ffmpeg_setup as fs

        if sys.platform == "darwin":
            assert fs._MAC_ZIPS[1].endswith("ffprobe/zip")
        else:
            for u in (*fs._WINDOWS_ZIPS, *fs._LINUX_ZIPS):
                assert u.startswith("https://")
