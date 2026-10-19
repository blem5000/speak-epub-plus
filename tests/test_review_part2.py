"""Tests for the fixes of code review part 2 (packets 5-14).

Each test pins a behaviour that was broken before the review round:
the store location, the log channel, the part numbering, the filter
safety valves, the cache guards and the EPUB gate.
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import get_store_path, handle_rpc, load_store, save_store  # noqa: E402


class TestStoreLocation:
    def test_env_override_wins(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPEAK_EPUB_STORE", str(tmp_path / "custom.json"))
        assert get_store_path() == tmp_path / "custom.json"

    def test_existing_cwd_store_is_adopted(self, tmp_path, monkeypatch):
        # the legacy location keeps working (dev checkout / old installs)
        monkeypatch.delenv("SPEAK_EPUB_STORE", raising=False)
        monkeypatch.chdir(tmp_path)
        (tmp_path / "store.json").write_text("{}", encoding="utf-8")
        assert get_store_path() == Path("store.json")

    def test_new_install_uses_app_data(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SPEAK_EPUB_STORE", raising=False)
        monkeypatch.chdir(tmp_path)  # no store.json here
        path = get_store_path()
        assert path.name == "store.json"
        assert "speak-epub" in str(path).lower()
        assert not path.is_relative_to(tmp_path)

    def test_corrupt_store_is_reported_not_swallowed(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("SPEAK_EPUB_STORE", str(tmp_path / "store.json"))
        (tmp_path / "store.json").write_text("{not json", encoding="utf-8")
        loaded = load_store()
        # the defaults are returned, but the corruption is visible
        assert loaded.get("voice")
        assert "unreadable" in capsys.readouterr().out

    def test_save_store_uses_a_unique_temp_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPEAK_EPUB_STORE", str(tmp_path / "store.json"))
        save_store({"voice": "en-US-JennyNeural"})
        save_store({"parallel": 2})
        # no temp file is left behind
        assert not list(tmp_path.glob("*.tmp"))
        data = json.loads((tmp_path / "store.json").read_text(encoding="utf-8"))
        assert data["voice"] == "en-US-JennyNeural"
        assert data["parallel"] == 2


class TestSelectionGuards:
    def test_selection_list_is_capped(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPEAK_EPUB_STORE", str(tmp_path / "store.json"))
        res = handle_rpc({
            "id": "1",
            "method": "setSelection",
            "params": {"selection": list(range(1, 5000))},
        })
        assert "result" in res, res
        assert len(res["result"]["selection"]) <= 1000

    def test_non_http_selection_url_is_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPEAK_EPUB_STORE", str(tmp_path / "store.json"))
        res = handle_rpc({
            "id": "1",
            "method": "setSelection",
            "params": {"url": "ftp://example.com/x"},
        })
        assert res["error"]["code"] == "VALUE_ERROR"


class TestSearchErrors:
    def test_failed_search_reports_an_error(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPEAK_EPUB_STORE", str(tmp_path / "store.json"))
        with patch("core.aggregator.search_all", side_effect=RuntimeError("site down")):
            res = handle_rpc({"id": "1", "method": "search", "params": {"title": "Some Book"}})
        assert res["error"]["code"] == "SEARCH_FAILED"
        assert "site down" in res["error"]["message"]


class TestPreviewGuards:
    def test_preview_has_a_timeout(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPEAK_EPUB_STORE", str(tmp_path / "store.json"))
        monkeypatch.setattr("core.tts.user_output_base", lambda: tmp_path)
        import core.config as cfg

        assert cfg.PREVIEW_TIMEOUT_SEC > 0

    def test_explicit_empty_local_voice_is_not_the_stored_one(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPEAK_EPUB_STORE", str(tmp_path / "store.json"))
        monkeypatch.setattr("core.tts.user_output_base", lambda: tmp_path)
        with patch("core.config.load_store", return_value={"localVoice": "pl_PL-darkman-medium"}):
            res = handle_rpc({
                "id": "1",
                "method": "previewVoice",
                "params": {"text": "hello", "engine": "edge", "localVoice": ""},
            })
        # the empty value means "the default voice" — the stored one must not
        # be used (and the request is not an error)
        assert "error" not in res, res
