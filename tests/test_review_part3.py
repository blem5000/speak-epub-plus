"""Tests for the fixes of review part 3 (core/tts.py, tts_local.py, fetch.py).

Each test pins a behaviour that was wrong before: the chunk-size clamp, the
lock owner liveness, the CUDA fallback and the model integrity check.
"""
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core.tts as tts  # noqa: E402
import core.tts_local as tts_local  # noqa: E402


class TestChunkSizeClamp:
    def test_above_the_edge_limit_is_clamped(self):
        # Edge TTS truncates above 5000 characters — the chunk size is
        # clamped instead of silently losing the tail of a chapter
        chunks = tts.split_text_for_tts("word " * 2000, 9000)
        assert all(len(c) <= tts.MAX_CHARS_PER_REQUEST for c in chunks)
        assert len(chunks) > 1

    def test_normal_size_is_untouched(self):
        chunks = tts.split_text_for_tts("word " * 100, 500)
        assert all(len(c) <= 500 for c in chunks)


class TestResumeLockOwner:
    def test_lock_of_a_dead_owner_is_reclaimed(self, tmp_path):
        lock = tmp_path / ".tts_resume.lock"
        # a lock left by a process that no longer exists (PID 999999)
        lock.write_text("999999", encoding="utf-8")
        # make it look fresh (not stale by mtime)
        os.utime(lock, None)
        acquired = tts.acquire_resume_lock(str(tmp_path))
        assert acquired is not None
        tts.release_resume_lock(acquired)

    def test_live_lock_is_not_stolen(self, tmp_path):
        lock = tmp_path / ".tts_resume.lock"
        lock.write_text(str(os.getpid()), encoding="utf-8")
        os.utime(lock, None)
        with pytest.raises(RuntimeError, match="concurrent resume"):
            tts.acquire_resume_lock(str(tmp_path))
        lock.unlink(missing_ok=True)


class TestCudaFallback:
    def test_requested_but_unavailable_uses_the_cpu(self, monkeypatch):
        monkeypatch.setenv("SPEAK_EPUB_PIPER_CUDA", "1")
        monkeypatch.setattr(tts_local, "cuda_available", lambda: False)
        assert tts_local.cuda_requested() is True
        assert tts_local.cuda_available() is False

    def test_not_requested(self, monkeypatch):
        monkeypatch.setenv("SPEAK_EPUB_PIPER_CUDA", "0")
        assert tts_local.cuda_requested() is False

    def test_env_var_wins_over_the_store(self, monkeypatch):
        monkeypatch.setenv("SPEAK_EPUB_PIPER_CUDA", "1")
        assert tts_local.cuda_requested() is True


class TestModelIntegrity:
    def test_digest_mismatch_marks_the_model_as_not_ready(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPEAK_EPUB_MODELS_DIR", str(tmp_path))
        monkeypatch.setattr(tts_local, "_piper_available", lambda: True)
        name = "en_US-lessac-medium"
        onnx, cfg = tts_local.local_voice_paths(name)
        onnx.parent.mkdir(parents=True, exist_ok=True)
        onnx.write_bytes(b"0" * 1_100_000)
        cfg.write_text("{}" * 40, encoding="utf-8")
        # no digest recorded yet -> the size checks decide
        assert tts_local.local_voice_ready(name) is True
        # a digest of something else -> the model is not usable
        tts_local._model_digest_path(name).write_text("0" * 64, encoding="utf-8")
        assert tts_local.local_voice_ready(name) is False
        # the real digest -> usable again
        tts_local._model_digest_path(name).write_text(
            f"{tts_local._file_sha256(onnx)}  {onnx.name}\n", encoding="utf-8"
        )
        assert tts_local.local_voice_ready(name) is True

    def test_config_must_not_be_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPEAK_EPUB_MODELS_DIR", str(tmp_path))
        monkeypatch.setattr(tts_local, "_piper_available", lambda: True)
        name = "en_US-lessac-medium"
        onnx, cfg = tts_local.local_voice_paths(name)
        onnx.parent.mkdir(parents=True, exist_ok=True)
        onnx.write_bytes(b"0" * 1_100_000)
        cfg.write_text("{}", encoding="utf-8")
        assert tts_local.local_voice_ready(name) is False
