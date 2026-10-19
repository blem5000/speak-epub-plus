# ffmpeg auto-repair: ensure_ffmpeg must repair a missing install rather
# than leaving "ffmpeg not found on PATH" to fail synthesis. All network
# and binaries are faked; no test downloads anything.
import io
import os
import sys
import urllib.error
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

    def _no_network(req, timeout=None):
        # no test may touch the network: a mirror that is not faked fails
        # instantly instead of waiting for a real download
        raise urllib.error.URLError("network disabled in tests")

    monkeypatch.setattr("core.ffmpeg_setup.urllib.request.urlopen", _no_network)
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

        # an existing install is only adopted when it actually runs
        with patch.object(fs, "_verify_binary", return_value=True):
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
        # staging: a failed install must not leave half an install behind
        assert not (fs.bin_dir() / "ffprobe.exe").is_file()
        assert not (fs.bin_dir() / "ffmpeg.exe").is_file()


class TestInstallHardening:
    def test_broken_existing_install_is_not_adopted(self, isolated_env, monkeypatch):
        """A half-extracted binary must be reinstalled, not adopted."""
        import core.ffmpeg_setup as fs

        bin_path = fs.bin_dir()
        bin_path.mkdir(parents=True)
        exe = bin_path / fs._exe_name("ffmpeg")
        exe.write_bytes(b"broken")

        # the existing binary does not run -> the install must be repaired
        def _verify(path):
            # only the PRE-EXISTING install is broken; the freshly downloaded
            # one works
            return str(path) != str(exe)

        monkeypatch.setattr(fs, "_verify_binary", _verify)
        monkeypatch.setattr(fs.urllib.request, "urlopen", lambda req, timeout=None: _FakeResp(_fake_ffmpeg_zip()))
        monkeypatch.setattr(fs.subprocess, "run", lambda args, **kw: SimpleNamespace(returncode=0))
        assert fs.ensure_ffmpeg() is True
        assert (bin_path / fs._exe_name("ffmpeg")).read_bytes() == b"fake-binary"

    def test_incomplete_download_is_rejected(self, isolated_env, monkeypatch):
        """A truncated archive must not be installed."""
        import core.ffmpeg_setup as fs

        class _TruncatedResp(_FakeResp):
            headers = {"Content-Length": "999999"}

        monkeypatch.setattr(
            fs.urllib.request, "urlopen", lambda req, timeout=None: _TruncatedResp(_fake_ffmpeg_zip())
        )
        monkeypatch.setattr(fs.subprocess, "run", lambda args, **kw: SimpleNamespace(returncode=0))
        assert fs.ensure_ffmpeg() is False
        assert not (fs.bin_dir() / fs._exe_name("ffmpeg")).is_file()

    def test_download_deadline(self, isolated_env, monkeypatch):
        """A trickling mirror must not stall the install forever."""
        import core.ffmpeg_setup as fs

        ticks = {"n": 0}

        def _fake_monotonic():
            ticks["n"] += 1
            return float(ticks["n"] * 10_000)

        monkeypatch.setattr(fs.time, "monotonic", _fake_monotonic)
        monkeypatch.setattr(fs.urllib.request, "urlopen", lambda req, timeout=None: _FakeResp(_fake_ffmpeg_zip()))
        with pytest.raises(TimeoutError):
            fs._download("https://example.invalid/a.zip", isolated_env / "a.zip", None)

    def test_incomplete_read_is_handled(self, isolated_env, monkeypatch):
        """A body that ends early must be reported, not crash the caller."""
        import http.client

        import core.ffmpeg_setup as fs

        def _raise_incomplete(req, timeout=None):
            raise http.client.IncompleteRead(b"partial")

        monkeypatch.setattr(fs.urllib.request, "urlopen", _raise_incomplete)
        monkeypatch.setattr(fs.subprocess, "run", lambda args, **kw: SimpleNamespace(returncode=0))
        # the exception is caught per mirror -> the install fails cleanly
        assert fs.ensure_ffmpeg() is False


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
