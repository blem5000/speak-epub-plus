"""Tests for the optional Kokoro engine tier (core/tts_kokoro.py).

Kokoro is a second offline engine next to Piper: higher quality, no output
token cap. Its Python packages ship as their own tier and the weights are a
separate on-demand download, so these tests pin the tier wiring, the voice
validation and the rate mapping — not the actual synthesis.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core.tts_kokoro as tts_kokoro  # noqa: E402


class TestVoiceCatalogue:
    def test_the_four_curated_voices_are_male_english(self):
        assert set(tts_kokoro.KOKORO_VOICES) == {
            "am_michael",
            "am_puck",
            "bm_daniel",
            "bm_george",
        }
        for vid, meta in tts_kokoro.KOKORO_VOICES.items():
            assert meta["gender"] == "male"
            assert meta["lang"] in ("en-us", "en-gb")
            # the id prefix must agree with the declared locale
            assert (vid[0] == "b") == (meta["lang"] == "en-gb")

    def test_default_voice_is_curated(self):
        assert tts_kokoro.DEFAULT_KOKORO_VOICE in tts_kokoro.KOKORO_VOICES

    def test_validate_accepts_a_curated_voice(self):
        assert tts_kokoro.validate_kokoro_voice("am_puck") == "am_puck"
        assert tts_kokoro.validate_kokoro_voice("  bm_george  ") == "bm_george"

    def test_validate_rejects_unknown_and_empty(self):
        with pytest.raises(ValueError):
            tts_kokoro.validate_kokoro_voice("xx_nobody")
        with pytest.raises(ValueError):
            tts_kokoro.validate_kokoro_voice("")
        with pytest.raises(ValueError):
            tts_kokoro.validate_kokoro_voice(None)


class TestRateMapping:
    def test_normal_rate_is_unity(self):
        assert tts_kokoro.rate_to_speed("+0%") == pytest.approx(1.0)

    def test_faster_rate_raises_speed(self):
        assert tts_kokoro.rate_to_speed("+25%") == pytest.approx(1.25)

    def test_slower_rate_lowers_speed(self):
        assert tts_kokoro.rate_to_speed("-25%") == pytest.approx(0.75)

    def test_speed_is_clamped_like_piper(self):
        assert tts_kokoro.rate_to_speed("+100%") == pytest.approx(2.0)
        assert tts_kokoro.rate_to_speed("-100%") == pytest.approx(0.75)

    def test_bare_number_is_accepted(self):
        """An int is a rate; a bare numeric STRING is garbage (no '%' sign).

        This mirrors normalize_tts_rate / the Piper mapping exactly: the two
        offline engines must interpret the same stored value identically, or
        switching engines would silently change the reading speed.
        """
        assert tts_kokoro.rate_to_speed(25) == pytest.approx(1.25)
        assert tts_kokoro.rate_to_speed("25") == pytest.approx(1.0)

    def test_matches_the_piper_mapping(self):
        from core.tts_local import rate_to_length_scale

        for value in ("+0%", "+25%", "-25%", "+100%", "-100%", 25, -10):
            piper_speed = 1.0 / rate_to_length_scale(value)
            assert tts_kokoro.rate_to_speed(value) == pytest.approx(piper_speed), value


class TestModelReadiness:
    def test_missing_files_mean_not_ready(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPEAK_EPUB_KOKORO_MODELS_DIR", str(tmp_path))
        assert tts_kokoro.kokoro_model_ready() is False

    def test_small_files_are_rejected(self, tmp_path, monkeypatch):
        """A truncated download must never count as ready."""
        monkeypatch.setenv("SPEAK_EPUB_KOKORO_MODELS_DIR", str(tmp_path))
        (tmp_path / tts_kokoro.MODEL_FILE).write_bytes(b"x" * 1024)
        (tmp_path / tts_kokoro.VOICES_FILE).write_bytes(b"x" * 1024)
        assert tts_kokoro.kokoro_model_ready() is False

    def test_plausible_sizes_are_ready(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPEAK_EPUB_KOKORO_MODELS_DIR", str(tmp_path))
        (tmp_path / tts_kokoro.MODEL_FILE).write_bytes(b"\0" * 50_000_001)
        (tmp_path / tts_kokoro.VOICES_FILE).write_bytes(b"\0" * 1_000_001)
        assert tts_kokoro.kokoro_model_ready() is True

    def test_ready_requires_the_engine_too(self, tmp_path, monkeypatch):
        """Model present but packages absent must not report ready."""
        monkeypatch.setenv("SPEAK_EPUB_KOKORO_MODELS_DIR", str(tmp_path))
        (tmp_path / tts_kokoro.MODEL_FILE).write_bytes(b"\0" * 50_000_001)
        (tmp_path / tts_kokoro.VOICES_FILE).write_bytes(b"\0" * 1_000_001)
        monkeypatch.setattr(tts_kokoro, "kokoro_available", lambda: False)
        assert tts_kokoro.kokoro_ready("am_michael") is False


class TestListPayload:
    def test_payload_lists_the_curated_voices(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPEAK_EPUB_KOKORO_MODELS_DIR", str(tmp_path))
        payload = tts_kokoro.list_kokoro_voices()
        ids = [v["id"] for v in payload["voices"]]
        assert ids == list(tts_kokoro.KOKORO_VOICES)
        assert payload["default"] == tts_kokoro.DEFAULT_KOKORO_VOICE
        assert payload["modelReady"] is False
        assert "modelsDir" in payload
        for v in payload["voices"]:
            assert v["gender"] == "male"
            assert isinstance(v["downloaded"], bool)


class TestEngineTier:
    def test_engine_root_is_overridable(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPEAK_EPUB_KOKORO_ENGINE_DIR", str(tmp_path / "k"))
        assert tts_kokoro.kokoro_engine_root() == tmp_path / "k"

    def test_engine_site_is_none_without_a_descriptor_hash(self, monkeypatch):
        monkeypatch.setattr(tts_kokoro, "_runtime_descriptor", lambda: {})
        assert tts_kokoro._engine_site() is None

    def test_ensure_reports_unavailable_without_a_descriptor(self, monkeypatch):
        monkeypatch.setattr(tts_kokoro, "kokoro_available", lambda: False)
        monkeypatch.setattr(tts_kokoro, "_runtime_descriptor", lambda: {})
        result = tts_kokoro.ensure_kokoro_engine()
        assert result["ok"] is False
        assert "not part of this build" in result["message"]


class TestDescriptorTiers:
    def test_split_tiers_separates_kokoro(self):
        from scripts.runtime_descriptor import split_tiers

        text = (
            "# --- core ---\nrequests==1\n"
            "# --- local ---\npiper-tts==1\n"
            "# --- kokoro ---\nkokoro-onnx==0.6.1\n"
        )
        core, local, kokoro = split_tiers(text)
        assert core == ["requests==1"]
        assert local == ["piper-tts==1"]
        assert kokoro == ["kokoro-onnx==0.6.1"]

    def test_split_requirements_stays_backward_compatible(self):
        from scripts.runtime_descriptor import split_requirements

        text = "# --- core ---\nrequests==1\n# --- local ---\npiper==1\n# --- kokoro ---\nk==1\n"
        core, local = split_requirements(text)
        assert core == ["requests==1"]
        assert local == ["piper==1"]

    def test_descriptor_carries_the_kokoro_tier(self):
        from scripts.runtime_descriptor import build_descriptor

        req = "# --- core ---\nrequests==1\n# --- local ---\npiper==1\n# --- kokoro ---\nk==1\n"
        d = build_descriptor("3.11.17+x", req, "https://example.com/releases/download/v1")
        assert len(d["kokoro_hash"]) == 16
        assert d["kokoro_asset"] == f"speak-epub-kokoro-{d['kokoro_hash']}.zip"

    def test_kokoro_hash_does_not_disturb_the_other_tiers(self):
        from scripts.runtime_descriptor import build_descriptor

        base = "# --- core ---\nrequests==1\n# --- local ---\npiper==1\n"
        a = build_descriptor("3.11.17+x", base)
        b = build_descriptor("3.11.17+x", base + "# --- kokoro ---\nk==1\n")
        # adding the Kokoro tier must not invalidate runtime or Piper caches
        assert a["hash"] == b["hash"]
        assert a["local_hash"] == b["local_hash"]
        assert a["kokoro_hash"] != b["kokoro_hash"]
