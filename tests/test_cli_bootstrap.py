"""Tests for the CLI runtime bootstrap (core/bootstrap.py).

The CLI must work without a prepared venv: the runtime tier is downloaded
once (the same release asset the desktop app uses) and cached in the user
profile. These tests pin the descriptor handling, the cache and the
download.
"""
import io
import json
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import bootstrap  # noqa: E402

DESCRIPTOR = {
    "format": 2,
    "hash": "abc123",
    "python_version": "3.11.17+20261013",
    "asset": "speak-epub-runtime-abc123.zip",
    "release_url": "https://github.com/owner/repo/releases/download/v1.2.3",
}


class TestDescriptor:
    def test_missing_descriptor_is_not_an_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(bootstrap, "descriptor_path", lambda: None)
        assert bootstrap.read_descriptor() == {}
        assert bootstrap.asset_url({}) is None

    def test_descriptor_is_read(self, tmp_path, monkeypatch):
        path = tmp_path / "runtime.json"
        path.write_text(json.dumps(DESCRIPTOR), encoding="utf-8")
        monkeypatch.setattr(bootstrap, "descriptor_path", lambda: path)
        data = bootstrap.read_descriptor()
        assert data["hash"] == "abc123"
        assert (
            bootstrap.asset_url(data)
            == "https://github.com/owner/repo/releases/download/v1.2.3/speak-epub-runtime-abc123.zip"
        )

    def test_broken_descriptor_is_ignored(self, tmp_path, monkeypatch):
        path = tmp_path / "runtime.json"
        path.write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(bootstrap, "descriptor_path", lambda: path)
        assert bootstrap.read_descriptor() == {}


class TestBackendDetection:
    def test_backend_available(self):
        assert bootstrap.backend_available() is True  # the dev venv has them

    def test_missing_module_is_detected(self):
        with patch("importlib.util.find_spec", side_effect=ImportError("no module")):
            assert bootstrap.backend_available() is False


class TestCache:
    def test_cache_root_is_overridable(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPEAK_EPUB_RUNTIME_DIR", str(tmp_path / "rt"))
        assert bootstrap.cache_root() == tmp_path / "rt"

    def test_cached_interpreter_found(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPEAK_EPUB_RUNTIME_DIR", str(tmp_path))
        target = tmp_path / "abc123" / "python"
        target.mkdir(parents=True)
        exe = target / ("python.exe" if sys.platform == "win32" else "python3")
        if sys.platform != "win32":
            (target / "bin").mkdir()
            exe = target / "bin" / "python3"
        exe.write_bytes(b"x")
        assert bootstrap.cached_interpreter(DESCRIPTOR) == exe

    def test_cached_interpreter_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPEAK_EPUB_RUNTIME_DIR", str(tmp_path))
        assert bootstrap.cached_interpreter(DESCRIPTOR) is None


class TestDownload:
    def _fake_zip(self) -> io.BytesIO:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            name = "python/python.exe" if sys.platform == "win32" else "python/bin/python3"
            zf.writestr(name, b"interpreter")
        buf.seek(0)
        return buf

    def test_download_extracts_and_caches(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPEAK_EPUB_RUNTIME_DIR", str(tmp_path / "cache"))
        payload = self._fake_zip()

        class _Resp:
            headers = {"Content-Length": str(len(payload.getvalue()))}

            def __init__(self):
                self._buf = payload

            def read(self, n=-1):
                chunk, self._buf = self._buf.read(n), io.BytesIO()
                return chunk

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with patch("urllib.request.urlopen", return_value=_Resp()):
            python = bootstrap.download_runtime(DESCRIPTOR)
        assert python is not None
        assert python.is_file()
        assert python.parent.name == ("python" if sys.platform == "win32" else "bin")
        # the cache is keyed by the hash
        assert (tmp_path / "cache" / "abc123").is_dir()

    def test_download_failure_is_reported(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPEAK_EPUB_RUNTIME_DIR", str(tmp_path / "cache"))
        with patch("urllib.request.urlopen", side_effect=OSError("network down")):
            assert bootstrap.download_runtime(DESCRIPTOR) is None

    def test_non_release_url_is_refused(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPEAK_EPUB_RUNTIME_DIR", str(tmp_path / "cache"))
        bad = dict(DESCRIPTOR, release_url="https://evil.example.com/x")
        with patch("urllib.request.urlopen") as urlopen:
            assert bootstrap.download_runtime(bad) is None
        urlopen.assert_not_called()

    def test_ensure_runtime_uses_the_current_interpreter(self):
        # the dev venv already has the dependencies -> nothing to do
        assert bootstrap.ensure_runtime() == Path(sys.executable)
