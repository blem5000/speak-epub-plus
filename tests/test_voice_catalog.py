"""Tests for the voice catalogue and single-chapter invalidation.

Three additions landed together:

* `listVoices` — the Edge catalogue (hundreds of voices) for the searchable
  picker in Settings. The GUI used to offer four hardcoded voices.
* the full upstream Piper catalogue (177 voices) instead of a five-voice
  shortlist — any upstream voice id must be accepted, downloaded and used.
* `rebuildChapter` — drops one chapter's artifacts so the next build
  regenerates just that chapter instead of the whole book.
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import handle_rpc  # noqa: E402
from core import tts_local  # noqa: E402
from core.tts import invalidate_chapter_artifacts  # noqa: E402

CATALOG = {
    "pl_PL-gosia-medium": {
        "key": "pl_PL-gosia-medium",
        "name": "gosia",
        "language": {"code": "pl_PL", "family": "pl", "name_english": "Polish"},
        "quality": "medium",
        "files": {
            "pl/pl_PL/gosia/medium/pl_PL-gosia-medium.onnx": {"size_bytes": 63201294},
            "pl/pl_PL/gosia/medium/pl_PL-gosia-medium.onnx.json": {"size_bytes": 4814},
        },
    },
    "en_US-lessac-medium": {
        "key": "en_US-lessac-medium",
        "name": "lessac",
        "language": {"code": "en_US", "family": "en", "name_english": "English (US)"},
        "quality": "medium",
        "files": {
            "en/en_US/lessac/medium/en_US-lessac-medium.onnx": {"size_bytes": 63201294},
        },
    },
}


def _coro(value):
    async def _run():
        return value

    return _run


def _raising(exc):
    async def _run():
        raise exc

    return _run


class TestEdgeCatalogueRpc:
    def test_returns_the_catalogue(self):
        voices = [
            {"ShortName": "pl-PL-ZofiaNeural", "Gender": "Female", "Locale": "pl-PL", "FriendlyName": "Zofia"},
            {"ShortName": "en-US-JennyNeural", "Gender": "Female", "Locale": "en-US", "FriendlyName": "Jenny"},
        ]
        with patch("edge_tts.list_voices", new=_coro(voices)):
            res = handle_rpc({"id": "1", "method": "listVoices", "params": {}})
        assert "error" not in res, res
        result = res["result"]
        assert result["total"] == 2
        ids = [v["id"] for v in result["voices"]]
        assert "pl-PL-ZofiaNeural" in ids
        zofia = next(v for v in result["voices"] if v["id"] == "pl-PL-ZofiaNeural")
        assert zofia["locale"] == "pl-PL"
        assert zofia["friendlyName"] == "Zofia"

    def test_entries_without_a_short_name_are_skipped(self):
        with patch("edge_tts.list_voices", new=_coro([{"Gender": "Female"}])):
            res = handle_rpc({"id": "1", "method": "listVoices", "params": {}})
        assert res["result"]["total"] == 0

    def test_a_failure_is_reported_as_an_error(self):
        with patch("edge_tts.list_voices", new=_raising(RuntimeError("offline"))):
            res = handle_rpc({"id": "1", "method": "listVoices", "params": {}})
        assert res["error"]["code"] == "EXCEPTION"


class TestPiperCatalogue:
    def test_catalogue_is_parsed_from_the_upstream_shape(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tts_local, "_catalog_path", lambda: tmp_path / "voices.json")
        monkeypatch.setattr(tts_local, "_PIPER_CATALOG_CACHE", {})
        monkeypatch.setattr(tts_local, "_PIPER_CATALOG_TTL_SEC", 0)
        with patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(CATALOG).encode("utf-8")
            voices = tts_local.piper_catalog()
        assert len(voices) == 2
        gosia = next(v for v in voices if v["id"] == "pl_PL-gosia-medium")
        assert gosia["language"] == "Polish"
        assert gosia["quality"] == "medium"
        assert gosia["sizeMb"] == 60
        assert gosia["recommended"] is True

    def test_catalogue_is_cached_on_disk(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tts_local, "_catalog_path", lambda: tmp_path / "voices.json")
        monkeypatch.setattr(tts_local, "_PIPER_CATALOG_CACHE", {})
        monkeypatch.setattr(tts_local, "_PIPER_CATALOG_TTL_SEC", 3600)
        with patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(CATALOG).encode("utf-8")
            tts_local.piper_catalog()
        assert (tmp_path / "voices.json").is_file()
        # the second call must not hit the network
        with patch("urllib.request.urlopen") as urlopen:
            voices = tts_local.piper_catalog()
        assert len(voices) == 2
        assert urlopen.call_count == 0

    def test_any_upstream_voice_is_accepted(self):
        assert tts_local.validate_local_voice("pl_PL-gosia-medium") == "pl_PL-gosia-medium"
        assert tts_local.validate_local_voice("pl_PL-bass-high") == "pl_PL-bass-high"
        with pytest.raises(ValueError):
            tts_local.validate_local_voice("not-a-voice")
        with pytest.raises(ValueError):
            tts_local.validate_local_voice(None)

    def test_download_of_a_non_shortlisted_voice_reports_its_size(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tts_local, "local_models_root", lambda: tmp_path)
        monkeypatch.setattr(tts_local, "_piper_available", lambda: True)
        monkeypatch.setattr(tts_local, "piper_catalog", lambda *a, **k: [
            {"id": "pl_PL-bass-high", "sizeMb": 108},
        ])
        monkeypatch.setattr(tts_local, "_voice_download_urls", lambda name: ("http://x/model.onnx", "http://x/model.onnx.json"))

        def _fake_fetch(url, dest, name, log):
            Path(dest).write_bytes(b"x" * 2_000_000)
            return None

        monkeypatch.setattr(tts_local, "_fetch_to_file", _fake_fetch)
        monkeypatch.setattr(tts_local, "_model_integrity_ok", lambda name: True)
        logs = []
        out = tts_local.download_local_voice("pl_PL-bass-high", on_log=logs.append)
        assert out["id"] == "pl_PL-bass-high"
        assert out["bytes"] > 0
        assert any("108 MB" in line for line in logs)

    def test_local_voice_ready_accepts_upstream_voices(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tts_local, "local_models_root", lambda: tmp_path)
        monkeypatch.setattr(tts_local, "_piper_available", lambda: True)
        monkeypatch.setattr(tts_local, "_model_integrity_ok", lambda name: True)
        onnx, cfg = tts_local.local_voice_paths("pl_PL-gosia-medium")
        onnx.write_bytes(b"x" * 2_000_000)
        cfg.write_text("{}" * 40)
        assert tts_local.local_voice_ready("pl_PL-gosia-medium") is True
        assert tts_local.local_voice_ready("nonsense") is False


class TestInvalidateChapterArtifacts:
    def test_only_the_given_chapter_is_removed(self, tmp_path):
        parts = tmp_path / "_parts"
        parts.mkdir()
        (tmp_path / "001_First.mp3").write_bytes(b"a")
        (tmp_path / "001_First.title.mp3").write_bytes(b"a")
        (tmp_path / "002_Second.mp3").write_bytes(b"b")
        (parts / "001_First_part001.mp3").write_bytes(b"a")
        (parts / "002_Second_part001.mp3").write_bytes(b"b")
        (tmp_path / "cover.jpg").write_bytes(b"c")

        removed = invalidate_chapter_artifacts(str(tmp_path), 1)
        assert sorted(removed) == ["001_First.mp3", "001_First.title.mp3", "001_First_part001.mp3"]
        assert (tmp_path / "002_Second.mp3").is_file()
        assert (parts / "002_Second_part001.mp3").is_file()
        assert (tmp_path / "cover.jpg").is_file()

    def test_a_missing_directory_is_not_an_error(self, tmp_path):
        assert invalidate_chapter_artifacts(str(tmp_path / "nope"), 1) == []

    def test_rpc_rebuild_chapter(self, tmp_path):
        (tmp_path / "003_Third.mp3").write_bytes(b"a")
        (tmp_path / "004_Fourth.mp3").write_bytes(b"b")
        res = handle_rpc(
            {
                "id": "1",
                "method": "rebuildChapter",
                "params": {"audioDir": str(tmp_path), "chapter": 3},
            }
        )
        assert "error" not in res, res
        assert res["result"]["chapter"] == 3
        assert not (tmp_path / "003_Third.mp3").exists()
        assert (tmp_path / "004_Fourth.mp3").exists()

    def test_rpc_rebuild_chapter_validates_its_input(self):
        res = handle_rpc({"id": "1", "method": "rebuildChapter", "params": {"chapter": 3}})
        assert res["error"]["code"] == "VALUE_ERROR"
        res = handle_rpc({"id": "1", "method": "rebuildChapter", "params": {"audioDir": "x", "chapter": 0}})
        assert res["error"]["code"] == "VALUE_ERROR"
        res = handle_rpc({"id": "1", "method": "rebuildChapter", "params": {"audioDir": "x", "chapter": "abc"}})
        assert res["error"]["code"] == "VALUE_ERROR"
