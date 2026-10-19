"""Tests for the previewVoice RPC (core/config.py).

The Settings screen sends the sample text plus the CURRENT voice/rate/engine
(local voice) so the clip matches what the user sees. The GUI test mocks the
sidecar, so nothing on this side was pinned: a regression here (wrong voice,
ignored rate, wrong engine) shipped green.
"""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import handle_rpc  # noqa: E402


def _preview(params, store=None):
    with patch("core.config.load_store", return_value=store or {}):
        return handle_rpc({"id": "1", "method": "previewVoice", "params": params})


@pytest.fixture(autouse=True)
def _preview_dir(tmp_path, monkeypatch):
    """Keep the preview output inside the test sandbox."""
    monkeypatch.setattr("core.tts.user_output_base", lambda: tmp_path)


class TestPreviewVoiceRpc:
    def test_text_is_required(self):
        res = _preview({"voice": "en-US-AriaNeural"})
        assert res["error"]["code"] == "VALUE_ERROR"
        assert "text must be non-empty" in res["error"]["message"]
        res = _preview({"text": "   "})
        assert res["error"]["code"] == "VALUE_ERROR"

    def test_invalid_engine_is_rejected(self):
        res = _preview({"text": "hello", "engine": "bogus"})
        assert res["error"]["code"] == "VALUE_ERROR"
        assert "invalid engine" in res["error"]["message"]

    def test_local_engine_without_model_is_rejected(self):
        res = _preview({"text": "hello", "engine": "local", "localVoice": "pl_PL-darkman-medium"})
        assert res["error"]["code"] == "VALUE_ERROR"
        assert "not downloaded" in res["error"]["message"]

    def test_edge_preview_forwards_voice_and_rate(self, tmp_path):
        captured = {}

        async def _fake_edge(text, out_path, voice, retries=5, rate=None, **kwargs):
            captured["text"] = text
            captured["voice"] = voice
            captured["rate"] = rate
            Path(out_path).write_bytes(b"mp3" * 100)

        with patch("core.tts.tts_text_to_mp3", side_effect=_fake_edge):
            with patch("core.config.load_store", return_value={}):
                res = handle_rpc({
                    "id": "1",
                    "method": "previewVoice",
                    "params": {
                        "text": "Witaj, tak brzmi próbka.",
                        "voice": "pl-PL-ZofiaNeural",
                        "rate": "+20%",
                        "engine": "edge",
                    },
                })
        assert "error" not in res, res
        assert res["result"]["engine"] == "edge"
        # the requested voice and rate must reach the synthesizer
        assert captured["voice"] == "pl-PL-ZofiaNeural"
        assert captured["rate"] == "+20%"
        assert captured["text"] == "Witaj, tak brzmi próbka."

    def test_rate_falls_back_to_the_store(self, tmp_path):
        captured = {}

        async def _fake_edge(text, out_path, voice, retries=5, rate=None, **kwargs):
            captured["rate"] = rate
            Path(out_path).write_bytes(b"mp3" * 100)

        with patch("core.tts.tts_text_to_mp3", side_effect=_fake_edge):
            with patch("core.config.load_store", return_value={"rate": "-10%"}):
                res = handle_rpc({
                    "id": "1",
                    "method": "previewVoice",
                    "params": {"text": "hello", "engine": "edge"},
                })
        assert "error" not in res, res
        assert captured["rate"] == "-10%"

    def test_malformed_rate_falls_back_to_normal_speed(self, tmp_path):
        captured = {}

        async def _fake_edge(text, out_path, voice, retries=5, rate=None, **kwargs):
            captured["rate"] = rate
            Path(out_path).write_bytes(b"mp3" * 100)

        with patch("core.tts.tts_text_to_mp3", side_effect=_fake_edge):
            with patch("core.config.load_store", return_value={}):
                res = handle_rpc({
                    "id": "1",
                    "method": "previewVoice",
                    "params": {"text": "hello", "engine": "edge", "rate": "abc"},
                })
        assert "error" not in res, res
        # a garbage rate must not be forwarded to the synthesizer
        assert captured["rate"] == "+0%"

    def test_voice_falls_back_to_the_store(self, tmp_path):
        captured = {}

        async def _fake_edge(text, out_path, voice, retries=5, rate=None, **kwargs):
            captured["voice"] = voice
            Path(out_path).write_bytes(b"mp3" * 100)

        with patch("core.tts.tts_text_to_mp3", side_effect=_fake_edge):
            with patch("core.config.load_store", return_value={"voice": "en-GB-SoniaNeural"}):
                res = handle_rpc({
                    "id": "1",
                    "method": "previewVoice",
                    "params": {"text": "hello", "engine": "edge"},
                })
        assert "error" not in res, res
        assert captured["voice"] == "en-GB-SoniaNeural"
