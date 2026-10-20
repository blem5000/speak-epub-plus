"""Tests for the optional local-engine tier (core/tts_local.py).

The Piper engine (piper + numpy + onnxruntime, ~60 MB) is a separate
download: the runtime tier ships without it. These tests pin the download
flow, the cache and the "already there" shortcut.
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

import core.tts_local as tts_local  # noqa: E402

DESCRIPTOR = {
    "format": 2,
    "hash": "runtimehash",
    "python_version": "3.11.17+20261013",
    "asset": "speak-epub-runtime-runtimehash.zip",
    "release_url": "https://github.com/owner/repo/releases/download/v9.9.9",
    "local_hash": "localhash",
    "local_asset": "speak-epub-local-localhash.zip",
}


@pytest.fixture()
def engine_env(tmp_path, monkeypatch):
    """Isolate the engine cache and point the descriptor at a known file."""
    monkeypatch.setenv("SPEAK_EPUB_LOCAL_ENGINE_DIR", str(tmp_path / "local"))
    monkeypatch.setattr(tts_local, "_runtime_descriptor", lambda: dict(DESCRIPTOR))
    return tmp_path


def _fake_zip(names: dict[str, bytes]) -> io.BytesIO:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in names.items():
            zf.writestr(name, data)
    buf.seek(0)
    return buf


class TestLocalEngine:
    def test_local_engine_root_is_overridable(self, engine_env, monkeypatch):
        monkeypatch.setenv("SPEAK_EPUB_LOCAL_ENGINE_DIR", str(engine_env / "other"))
        assert tts_local.local_engine_root() == engine_env / "other"

    def test_download_extracts_and_marks_ready(self, engine_env, monkeypatch):
        payload = _fake_zip({"piper/__init__.py": b"# piper", "numpy/__init__.py": b"# numpy"})
        seen = {}
        # the engine is missing until the download finished
        state = {"ready": False}

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

        def fake_urlopen(req, timeout=None):
            seen["url"] = getattr(req, "full_url", str(req))
            state["ready"] = True
            return _Resp()

        monkeypatch.setattr(tts_local, "local_engine_available", lambda: state["ready"])
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = tts_local.ensure_local_engine()

        assert result["ok"] is True, result
        assert result["downloaded"] is True
        assert seen["url"].endswith("speak-epub-local-localhash.zip"), seen
        target = tts_local.local_engine_root() / "localhash"
        assert (target / "piper" / "__init__.py").is_file()
        assert (target / ".ready").is_file()

    def test_second_call_does_not_download_again(self, engine_env, monkeypatch):
        target = tts_local.local_engine_root() / "localhash"
        (target).mkdir(parents=True, exist_ok=True)
        (target / "piper").mkdir(exist_ok=True)
        (target / ".ready").write_text("ok", encoding="utf-8")
        monkeypatch.setattr(tts_local, "local_engine_available", lambda: True)

        def boom(*a, **kw):
            raise AssertionError("must not download again")

        with patch("urllib.request.urlopen", side_effect=boom):
            result = tts_local.ensure_local_engine()
        assert result["ok"] is True
        assert result["downloaded"] is False

    def test_missing_descriptor_is_reported(self, engine_env, monkeypatch):
        monkeypatch.setattr(tts_local, "_runtime_descriptor", lambda: {})
        monkeypatch.setattr(tts_local, "local_engine_available", lambda: False)
        result = tts_local.ensure_local_engine()
        assert result["ok"] is False
        assert "not part of this build" in result["message"]

    def test_download_failure_is_reported(self, engine_env, monkeypatch):
        monkeypatch.setattr(tts_local, "local_engine_available", lambda: False)

        def boom(*a, **kw):
            raise OSError("network down")

        with patch("urllib.request.urlopen", side_effect=boom):
            result = tts_local.ensure_local_engine()
        assert result["ok"] is False
        assert "download failed" in result["message"]

    def test_engine_available_checks_the_import(self, engine_env, monkeypatch):
        with patch("core.tts_local.importlib.import_module", side_effect=ImportError("no piper")):
            assert tts_local.local_engine_available() is False
        with patch("core.tts_local.importlib.import_module", return_value=object()):
            assert tts_local.local_engine_available() is True
