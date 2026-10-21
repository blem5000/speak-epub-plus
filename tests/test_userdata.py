"""Tests for the per-user data: search history, library, pronunciation.

These three features share one module (`core/userdata.py`) and one place
per file in the user data directory. The files are the source of truth —
the GUI only mirrors them.
"""
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import handle_rpc  # noqa: E402
from core import userdata  # noqa: E402


@pytest.fixture(autouse=True)
def _user_data(tmp_path, monkeypatch):
    """Every test gets its own data directory."""
    monkeypatch.setenv("SPEAK_EPUB_STORE", str(tmp_path / "store.json"))
    return tmp_path


class TestSearchHistory:
    def test_the_most_recent_search_comes_first(self):
        userdata.add_search_history("Wiedzmin")
        userdata.add_search_history("Zamkniete Drzwi")
        history = userdata.get_search_history()
        assert [h["query"] for h in history] == ["Zamkniete Drzwi", "Wiedzmin"]

    def test_the_same_query_is_not_duplicated(self):
        userdata.add_search_history("Wiedzmin")
        userdata.add_search_history("wiedzmin")
        assert len(userdata.get_search_history()) == 1

    def test_blank_queries_are_ignored(self):
        userdata.add_search_history("   ")
        assert userdata.get_search_history() == []

    def test_the_history_is_bounded(self):
        for i in range(userdata.MAX_HISTORY + 10):
            userdata.add_search_history(f"query {i}")
        assert len(userdata.get_search_history()) == userdata.MAX_HISTORY

    def test_clearing(self):
        userdata.add_search_history("Wiedzmin")
        userdata.clear_search_history()
        assert userdata.get_search_history() == []

    def test_a_corrupt_file_yields_an_empty_history(self):
        path = userdata.data_path("search-history.json")
        path.write_text("{not json", encoding="utf-8")
        assert userdata.get_search_history() == []

    def test_rpc_round_trip(self):
        res = handle_rpc({"id": "1", "method": "addSearchHistory", "params": {"query": "Wiedzmin"}})
        assert "error" not in res, res
        assert res["result"]["history"][0]["query"] == "Wiedzmin"
        res = handle_rpc({"id": "2", "method": "getSearchHistory", "params": {}})
        assert res["result"]["history"][0]["query"] == "Wiedzmin"
        res = handle_rpc({"id": "3", "method": "clearSearchHistory", "params": {}})
        assert res["result"]["history"] == []


class TestLibrary:
    def test_an_entry_is_added(self):
        res = handle_rpc(
            {
                "id": "1",
                "method": "addLibraryEntry",
                "params": {
                    "path": "C:/out/book.m4b",
                    "title": "Wiedzmin",
                    "author": "Sapkowski",
                    "format": "m4b",
                    "size": 12345,
                    "chapters": 12,
                },
            }
        )
        assert "error" not in res, res
        entry = res["result"]["library"][0]
        assert entry["path"] == "C:/out/book.m4b"
        assert entry["title"] == "Wiedzmin"
        assert entry["chapters"] == 12

    def test_the_same_path_is_replaced_not_duplicated(self):
        for title in ("Pierwszy build", "Drugi build"):
            handle_rpc(
                {
                    "id": "1",
                    "method": "addLibraryEntry",
                    "params": {"path": "C:/out/book.m4b", "title": title},
                }
            )
        library = userdata.get_library()
        assert len(library) == 1
        assert library[0]["title"] == "Drugi build"

    def test_an_entry_without_a_path_is_ignored(self):
        res = handle_rpc({"id": "1", "method": "addLibraryEntry", "params": {"title": "x"}})
        assert res["result"]["library"] == []

    def test_removing_forgets_the_entry_but_not_the_file(self, tmp_path):
        target = tmp_path / "book.m4b"
        target.write_bytes(b"x")
        handle_rpc(
            {"id": "1", "method": "addLibraryEntry", "params": {"path": str(target)}}
        )
        res = handle_rpc(
            {"id": "2", "method": "removeLibraryEntry", "params": {"path": str(target)}}
        )
        assert res["result"]["library"] == []
        assert target.is_file()

    def test_the_library_survives_a_restart(self):
        handle_rpc(
            {"id": "1", "method": "addLibraryEntry", "params": {"path": "C:/out/book.m4b"}}
        )
        raw = json.loads(userdata.data_path("library.json").read_text(encoding="utf-8"))
        assert raw[0]["path"] == "C:/out/book.m4b"


class TestPronunciation:
    def test_a_word_is_replaced(self):
        userdata.set_pronunciation([{"from": "Arystoteles", "to": "ary-stoteles"}])
        out = userdata.apply_pronunciation("Arystoteles byl filozofem.")
        assert out == "ary-stoteles byl filozofem."

    def test_the_case_does_not_matter(self):
        userdata.set_pronunciation([{"from": "Arystoteles", "to": "ary-stoteles"}])
        assert "ary-stoteles" in userdata.apply_pronunciation("arystoteles byl filozofem.")

    def test_only_whole_words_are_replaced(self):
        userdata.set_pronunciation([{"from": "Jan", "to": "Yahn"}])
        out = userdata.apply_pronunciation("Jan mial syna Jana.")
        assert "Yahn mial" in out
        # "Jana" is a different word and stays untouched
        assert "Jana" in out

    def test_the_longer_entry_wins(self):
        userdata.set_pronunciation(
            [{"from": "Jan", "to": "Yahn"}, {"from": "Jan Kowalski", "to": "Yahn Kowalski"}]
        )
        out = userdata.apply_pronunciation("Jan Kowalski i Jan.")
        assert "Yahn Kowalski i Yahn." == out

    def test_an_empty_dictionary_changes_nothing(self):
        assert userdata.apply_pronunciation("Nic sie nie zmienia.") == "Nic sie nie zmienia."

    def test_entries_are_deduplicated(self):
        entries = userdata.set_pronunciation(
            [{"from": "Jan", "to": "Yahn"}, {"from": "jan", "to": "Jan"}]
        )
        assert len(entries) == 1
        assert entries[0]["to"] == "Yahn"

    def test_incomplete_entries_are_dropped(self):
        entries = userdata.set_pronunciation([{"from": "Jan", "to": ""}, {"from": "", "to": "x"}])
        assert entries == []

    def test_rpc_round_trip(self):
        res = handle_rpc(
            {
                "id": "1",
                "method": "setPronunciation",
                "params": {"entries": [{"from": "Arystoteles", "to": "ary-stoteles"}]},
            }
        )
        assert "error" not in res, res
        assert res["result"]["entries"][0]["from"] == "Arystoteles"
        res = handle_rpc({"id": "2", "method": "getPronunciation", "params": {}})
        assert res["result"]["entries"][0]["to"] == "ary-stoteles"

    def test_rpc_rejects_a_non_list(self):
        res = handle_rpc(
            {"id": "1", "method": "setPronunciation", "params": {"entries": "nope"}}
        )
        assert res["error"]["code"] == "VALUE_ERROR"

    def test_the_plan_applies_the_dictionary(self, tmp_path):
        from core.tts import build_generation_plan

        userdata.set_pronunciation([{"from": "Arystoteles", "to": "ary-stoteles"}])
        plans, jobs = build_generation_plan(
            [(1, "Rozdzial", "Arystoteles mial syna.")], str(tmp_path / "out"), 3500
        )
        assert jobs, "the chapter must be queued"
        assert "ary-stoteles" in jobs[0].text
        assert "Arystoteles" not in jobs[0].text
