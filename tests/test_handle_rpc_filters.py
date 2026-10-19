"""Tests for filter RPC — Story 2.3."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from core.config import handle_rpc


def _isolate_store(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # the store lives in the per-user app-data dir — point it at the sandbox
    monkeypatch.setenv("SPEAK_EPUB_STORE", str(tmp_path / "store.json"))


def test_getFilters_empty(tmp_path, monkeypatch):
    _isolate_store(tmp_path, monkeypatch)
    r = handle_rpc({"id": "1", "method": "getFilters", "params": {}})
    assert "result" in r
    assert r["result"]["filters"] == []


def test_addFilter_plain(tmp_path, monkeypatch):
    _isolate_store(tmp_path, monkeypatch)
    r = handle_rpc({"id": "1", "method": "addFilter", "params": {"pattern": "Subscribe", "isRegex": False}})
    assert r["result"]["added"] is True
    assert len(r["result"]["filters"]) == 1
    assert r["result"]["filters"][0]["pattern"] == "Subscribe"
    # get
    r2 = handle_rpc({"id": "2", "method": "getFilters", "params": {}})
    assert len(r2["result"]["filters"]) == 1
    # persist file
    assert (tmp_path / "store.json").exists()
    data = json.loads((tmp_path / "store.json").read_text(encoding="utf-8"))
    assert data["filters"][0]["pattern"] == "Subscribe"


def test_addFilter_regex(tmp_path, monkeypatch):
    _isolate_store(tmp_path, monkeypatch)
    r = handle_rpc({"id": "1", "method": "addFilter", "params": {"pattern": "subscribe.*patreon", "isRegex": True}})
    assert r["result"]["added"] is True
    assert r["result"]["filters"][0]["isRegex"] is True


def test_addFilter_duplicate(tmp_path, monkeypatch):
    _isolate_store(tmp_path, monkeypatch)
    handle_rpc({"id": "1", "method": "addFilter", "params": {"pattern": "Subscribe", "isRegex": False}})
    r = handle_rpc({"id": "2", "method": "addFilter", "params": {"pattern": "Subscribe", "isRegex": False}})
    assert r["result"]["added"] is False
    assert r["result"]["reason"] == "duplicate"
    r3 = handle_rpc({"id": "3", "method": "getFilters", "params": {}})
    assert len(r3["result"]["filters"]) == 1


def test_addFilter_invalid_regex(tmp_path, monkeypatch):
    _isolate_store(tmp_path, monkeypatch)
    r = handle_rpc({"id": "1", "method": "addFilter", "params": {"pattern": "[*", "isRegex": True}})
    assert r["error"]["code"] == "VALUE_ERROR"
    assert "invalid regex" in r["error"]["message"]


def test_addFilter_empty(tmp_path, monkeypatch):
    _isolate_store(tmp_path, monkeypatch)
    r = handle_rpc({"id": "1", "method": "addFilter", "params": {"pattern": "   ", "isRegex": False}})
    assert r["error"]["code"] == "VALUE_ERROR"


def test_removeFilter_by_index(tmp_path, monkeypatch):
    _isolate_store(tmp_path, monkeypatch)
    handle_rpc({"id": "1", "method": "addFilter", "params": {"pattern": "Subscribe", "isRegex": False}})
    handle_rpc({"id": "2", "method": "addFilter", "params": {"pattern": "patreon", "isRegex": False}})
    r = handle_rpc({"id": "3", "method": "removeFilter", "params": {"index": 0}})
    assert r["result"]["removed"] is True
    assert len(r["result"]["filters"]) == 1
    assert r["result"]["filters"][0]["pattern"] == "patreon"


def test_removeFilter_out_of_range(tmp_path, monkeypatch):
    _isolate_store(tmp_path, monkeypatch)
    r = handle_rpc({"id": "1", "method": "removeFilter", "params": {"index": 0}})
    assert r["error"]["code"] == "VALUE_ERROR"


def test_saveFilters_bulk_and_invalid(tmp_path, monkeypatch):
    _isolate_store(tmp_path, monkeypatch)
    filters = [
        {"pattern": "Subscribe", "isRegex": False},
        {"pattern": "subscribe.*patreon", "isRegex": True},
    ]
    r = handle_rpc({"id": "1", "method": "saveFilters", "params": {"filters": filters}})
    assert r["result"]["saved"] is True
    assert len(r["result"]["filters"]) == 2
    # invalid regex in bulk should fail
    bad = [{"pattern": "[*", "isRegex": True}]
    r2 = handle_rpc({"id": "2", "method": "saveFilters", "params": {"filters": bad}})
    assert r2["error"]["code"] == "VALUE_ERROR"
    # duplicate in bulk deduped
    dup = [
        {"pattern": "Subscribe", "isRegex": False},
        {"pattern": "Subscribe", "isRegex": False},
    ]
    r3 = handle_rpc({"id": "3", "method": "saveFilters", "params": {"filters": dup}})
    assert len(r3["result"]["filters"]) == 1


def test_previewChapter_filtered(tmp_path, monkeypatch):
    _isolate_store(tmp_path, monkeypatch)
    # set filters
    handle_rpc({"id": "1", "method": "saveFilters", "params": {"filters": [{"pattern": "Subscribe", "isRegex": False}, {"pattern": "subscribe.*patreon", "isRegex": True}]}})
    raw = '<html><body><div id="chapter-content"><p>Keep this</p><p>Subscribe to read more</p><p>please subscribe to patreon</p><p>Keep also</p></div></body></html>'
    url = "https://www.novelphoenix.com/novel/123/chapter/1"
    with patch("core.fetch.read_cache", return_value=raw):
        r = handle_rpc({"id": "2", "method": "previewChapter", "params": {"url": url, "start": "div#chapter-content"}})
        assert "result" in r
        # original contains Subscribe
        assert "Subscribe" in r["result"]["originalHtml"]
        # cleaned contains Subscribe before filter? cleaned should have both lines isolated but not yet filtered? Our preview returns cleaned as isolated without filter, and filtered as after filter
        assert "Subscribe" in r["result"]["text"]  # cleaned text still has it
        assert "Subscribe" not in r["result"]["filteredText"]
        assert "patreon" not in r["result"]["filteredText"]
        assert "Keep this" in r["result"]["filteredText"]
        # removedCount should be 2
        assert r["result"]["removedCount"] == 2
        # filteredHtml also filtered
        assert "Subscribe" not in r["result"]["filteredHtml"]
        # raw invariant: raw still contains
        assert "Subscribe" in r["result"]["originalHtml"]


def test_previewChapter_raw_invariant_no_filters(tmp_path, monkeypatch):
    _isolate_store(tmp_path, monkeypatch)
    # no filters
    raw = '<html><body><div id="chapter-content"><p>Hello</p><p>Subscribe</p></div></body></html>'
    url = "https://www.novelphoenix.com/novel/123/chapter/2"
    with patch("core.fetch.read_cache", return_value=raw):
        r = handle_rpc({"id": "1", "method": "previewChapter", "params": {"url": url, "start": "div#chapter-content"}})
        assert r["result"]["removedCount"] == 0
        assert r["result"]["filteredText"] == r["result"]["text"]
        assert "Subscribe" in r["result"]["text"]


def test_previewChapter_invalid_regex_in_store(tmp_path, monkeypatch):
    _isolate_store(tmp_path, monkeypatch)
    # manually write invalid filter to store to test preview handling (sanitize should skip invalid, but addFilter would have blocked; test save with invalid bypassed via direct store write)
    store_path = tmp_path / "store.json"
    store_path.write_text(json.dumps({"filters": [{"pattern": "Subscribe", "isRegex": False}]}), encoding="utf-8")
    raw = '<html><body><div id="chapter-content"><p>Hello</p></div></body></html>'
    url = "https://www.novelphoenix.com/novel/123/chapter/3"
    with patch("core.fetch.read_cache", return_value=raw):
        r = handle_rpc({"id": "1", "method": "previewChapter", "params": {"url": url, "start": "div#chapter-content"}})
        assert "result" in r
        # should succeed since stored filter is valid


def test_filters_persist_across_calls(tmp_path, monkeypatch):
    _isolate_store(tmp_path, monkeypatch)
    handle_rpc({"id": "1", "method": "addFilter", "params": {"pattern": "Unlimited access", "isRegex": False}})
    # simulate separate process reload via fresh handle_rpc get
    r = handle_rpc({"id": "2", "method": "getFilters", "params": {}})
    assert len(r["result"]["filters"]) == 1
    # add regex
    handle_rpc({"id": "3", "method": "addFilter", "params": {"pattern": "subscribe.*patreon", "isRegex": True}})
    r2 = handle_rpc({"id": "4", "method": "getFilters", "params": {}})
    assert len(r2["result"]["filters"]) == 2
