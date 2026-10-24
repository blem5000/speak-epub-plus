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

    def test_malformed_rate_is_rejected(self, tmp_path):
        # a garbage rate must fail the preview exactly like it fails the
        # build — a silent "+0%" made the sample disagree with the build
        res = _preview({"text": "hello", "engine": "edge", "rate": "abc"})
        assert res["error"]["code"] == "VALUE_ERROR"
        assert "invalid rate" in res["error"]["message"]

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


class TestPreviewVoiceKokoro:
    """Kokoro voice ids live in a separate namespace from Piper model ids.

    Regressions pinned here (all found by reviewing v0.3.22, fixed in v0.3.23):

    1. previewVoice read only `localVoice` and validated it as a Kokoro voice,
       so the UI's own payload failed with
       "unknown Kokoro voice 'en_US-ryan-high'".
    2. A stored `kokoroVoice` was never consulted, so a caller that omitted it
       silently previewed the default voice.
    3. The Piper id was validated eagerly, before the engine was known, so a
       Kokoro preview was rejected with "unknown local voice".
    4. A genuine synthesis error was caught as "already inside a loop" and
       retried, hiding the real message behind
       "a coroutine was expected, got <function ...>".
    """

    def _ready(self, monkeypatch):
        """Kokoro reports ready, and voice validation passes ids through."""
        import core.tts_kokoro as tk

        monkeypatch.setattr(tk, "kokoro_ready", lambda v: True)
        monkeypatch.setattr(
            tk, "validate_kokoro_voice", lambda v: (v or "").strip() or "am_michael"
        )
        return tk

    def test_the_kokoro_voice_field_is_used_and_the_piper_id_ignored(self, monkeypatch):
        tk = self._ready(monkeypatch)
        captured = {}

        def _fake(text, out_path, voice, retries=5, rate=None, **kw):
            captured["voice"] = voice
            Path(out_path).write_bytes(b"mp3" * 100)

        monkeypatch.setattr(tk, "tts_text_to_mp3_kokoro", _fake)

        res = _preview(
            {
                "text": "hello",
                "engine": "kokoro",
                "kokoroVoice": "bm_daniel",
                # a stale PIPER id must not be mistaken for a Kokoro voice
                "localVoice": "en_US-ryan-high",
            }
        )
        assert "error" not in res, res
        assert res["result"]["engine"] == "kokoro"
        assert captured["voice"] == "bm_daniel"

    def test_a_stored_kokoro_voice_is_used_when_the_caller_omits_it(self, monkeypatch):
        tk = self._ready(monkeypatch)
        captured = {}

        def _fake(text, out_path, voice, retries=5, rate=None, **kw):
            captured["voice"] = voice
            Path(out_path).write_bytes(b"mp3" * 100)

        monkeypatch.setattr(tk, "tts_text_to_mp3_kokoro", _fake)

        res = _preview(
            {"text": "hello", "engine": "kokoro"},
            store={"kokoroVoice": "bm_george"},
        )
        assert "error" not in res, res
        assert captured["voice"] == "bm_george"

    def test_the_piper_voice_is_not_validated_for_a_kokoro_preview(self, monkeypatch):
        """Piper ids must be ignored entirely when Kokoro speaks."""
        tk = self._ready(monkeypatch)
        monkeypatch.setattr(tk, "tts_text_to_mp3_kokoro", lambda t, o, v, retries=5, rate=None, **k: Path(o).write_bytes(b"m" * 100))

        # `en_US-ryan-high` is a real Piper id and NOT a Kokoro id: validating
        # it against the Kokoro catalogue is what produced the user-visible
        # "unknown Kokoro voice 'en_US-ryan-high'".
        res = _preview(
            {"text": "hello", "engine": "kokoro", "localVoice": "en_US-ryan-high"}
        )
        assert "error" not in res, res
        assert res["result"]["engine"] == "kokoro"

    def test_auto_prefers_kokoro_exactly_like_the_build(self, monkeypatch):
        """`auto` must resolve to the same engine in the preview and the build."""
        from unittest.mock import patch as _patch

        tk = self._ready(monkeypatch)
        captured = {}

        def _fake(text, out_path, voice, retries=5, rate=None, **kw):
            captured["engine"] = "kokoro"
            Path(out_path).write_bytes(b"mp3" * 100)

        monkeypatch.setattr(tk, "tts_text_to_mp3_kokoro", _fake)

        # even with a Piper voice ready, run_part_jobs checks Kokoro first
        with _patch("core.tts_local.local_voice_ready", return_value=True):
            res = _preview(
                {"text": "hello", "engine": "auto", "kokoroVoice": "am_puck"},
                store={"localVoice": "en_US-ryan-high"},
            )
        assert "error" not in res, res
        assert res["result"]["engine"] == "kokoro"

    def test_a_synthesis_error_surfaces_instead_of_a_coroutine_complaint(self, monkeypatch):
        """The real failure must reach the user, not a loop-handling artefact."""
        tk = self._ready(monkeypatch)

        def _boom(*a, **k):
            raise RuntimeError("the synthesizer exploded")

        monkeypatch.setattr(tk, "tts_text_to_mp3_kokoro", _boom)

        res = _preview({"text": "hello", "engine": "kokoro", "kokoroVoice": "am_puck"})
        assert res["error"]["code"] == "EXCEPTION", res
        assert "the synthesizer exploded" in res["error"]["message"]
        assert "coroutine was expected" not in res["error"]["message"]
