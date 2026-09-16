"""Tests for previewChapter / getSelectors / saveSelectors / clearSelectors RPC (2.2)."""
import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from core.config import handle_rpc
from core.ports import Selectors


def _valid_url():
    return "https://www.novelphoenix.com/novel/123/chapter/42"


def test_getSelectors_default_and_override(tmp_path, monkeypatch):
    # patch overrides dir to tmp
    import core.clean as clean
    monkeypatch.setattr(clean, "_OVERRIDES_DIR", tmp_path / "overrides")
    r = handle_rpc({"id": "1", "method": "getSelectors", "params": {"url": _valid_url()}})
    assert "result" in r
    assert r["result"]["site"] == "novelphoenix.com"
    assert r["result"]["start"] == "div#chapter-content"
    assert r["result"]["defaultStart"] == "div#chapter-content"
    assert r["result"]["override"] is None
    # save
    r2 = handle_rpc({"id": "2", "method": "saveSelectors", "params": {"url": _valid_url(), "start": ".custom", "end": None}})
    assert r2["result"]["saved"] is True
    r3 = handle_rpc({"id": "3", "method": "getSelectors", "params": {"url": _valid_url()}})
    assert r3["result"]["start"] == ".custom"
    assert r3["result"]["override"] == {"start": ".custom", "end": None}
    # clear
    r4 = handle_rpc({"id": "4", "method": "clearSelectors", "params": {"url": _valid_url()}})
    assert r4["result"]["cleared"] is True
    r5 = handle_rpc({"id": "5", "method": "getSelectors", "params": {"url": _valid_url()}})
    assert r5["result"]["override"] is None


def test_saveSelectors_invalid_selector(tmp_path, monkeypatch):
    import core.clean as clean
    monkeypatch.setattr(clean, "_OVERRIDES_DIR", tmp_path / "overrides")
    r = handle_rpc({"id": "1", "method": "saveSelectors", "params": {"url": _valid_url(), "start": "???", "end": None}})
    assert r["error"]["code"] == "VALUE_ERROR"
    assert "invalid selector" in r["error"]["message"]


def test_saveSelectors_unsupported_host():
    r = handle_rpc({"id": "1", "method": "saveSelectors", "params": {"url": "https://evil.com/chapter/1", "start": ".a", "end": None}})
    assert r["error"]["code"] == "LIST_FAILED"

def test_getSelectors_www_normalization(tmp_path, monkeypatch):
    import core.clean as clean
    monkeypatch.setattr(clean, "_OVERRIDES_DIR", tmp_path / "overrides")
    # save via www
    r = handle_rpc({"id": "1", "method": "saveSelectors", "params": {"url": "https://www.novelphoenix.com/novel/123/chapter/1", "start": ".www", "end": None}})
    assert r["result"]["saved"] is True
    # get via without www should see same override (canonical)
    r2 = handle_rpc({"id": "2", "method": "getSelectors", "params": {"url": "https://novelphoenix.com/novel/123/chapter/1"}})
    assert r2["result"]["start"] == ".www"


def test_previewChapter_cache_hit(tmp_path, monkeypatch):
    import core.clean as clean
    monkeypatch.setattr(clean, "_OVERRIDES_DIR", tmp_path / "overrides")
    raw = '<html><body><div id="chapter-content"><p>Real content</p><nav>nav</nav></div></body></html>'
    # mock read_cache to return raw
    with patch("core.fetch.read_cache", return_value=raw):
        r = handle_rpc({"id": "1", "method": "previewChapter", "params": {"url": _valid_url(), "start": "div#chapter-content"}})
        assert "result" in r
        assert "Real content" in r["result"]["text"]
        assert "nav" not in r["result"]["text"]
        assert r["result"]["originalHtml"] == raw
        assert "Real content" in r["result"]["originalText"]


def test_previewChapter_invalid_selector():
    raw = '<html><body><div id="chapter-content"><p>Real</p></div></body></html>'
    with patch("core.fetch.read_cache", return_value=raw):
        r = handle_rpc({"id": "1", "method": "previewChapter", "params": {"url": _valid_url(), "start": "???"}})
        assert r["error"]["code"] == "VALUE_ERROR"
        assert "invalid selector" in r["error"]["message"]


def test_previewChapter_end_selector():
    raw = '<html><body><div id="start">A</div><div>B</div><div id="end">C</div><div>D</div></body></html>'
    with patch("core.fetch.read_cache", return_value=raw):
        r = handle_rpc({"id": "1", "method": "previewChapter", "params": {"url": _valid_url(), "start": "#start", "end": "#end"}})
        assert "A" in r["result"]["text"]
        assert "B" in r["result"]["text"]
        assert "C" not in r["result"]["text"]


def test_previewChapter_no_cache_fallback_missing():
    # when both cache and core.http._get fail, should return LIST_FAILED
    with patch("core.fetch.read_cache", return_value=None):
        with patch("core.http._get", side_effect=Exception("network fail")):
            r = handle_rpc({"id": "1", "method": "previewChapter", "params": {"url": _valid_url(), "start": "div#chapter-content"}})
            assert r["error"]["code"] == "LIST_FAILED"


def test_previewChapter_no_cache_uses_core_http_fallback(tmp_path, monkeypatch):
    # Matrix: config fallback fetch — no cache, core/http._get used, response
    # handling identical to before (resp.text), still selector-isolated.
    import core.clean as clean
    monkeypatch.setattr(clean, "_OVERRIDES_DIR", tmp_path / "overrides")
    raw = '<html><body><div id="chapter-content"><p>Fresh body</p><nav>nav</nav></div></body></html>'
    mock_resp = Mock()
    mock_resp.text = raw
    with patch("core.fetch.read_cache", return_value=None):
        with patch("core.http._get", return_value=mock_resp) as mock_get:
            r = handle_rpc({"id": "1", "method": "previewChapter", "params": {"url": _valid_url(), "start": "div#chapter-content"}})
            assert "result" in r
            assert "Fresh body" in r["result"]["text"]
            assert "nav" not in r["result"]["text"]
            mock_get.assert_called_once()
            args, kwargs = mock_get.call_args
            assert args[0] == _valid_url()
            assert kwargs.get("timeout") == 12
            assert kwargs.get("retries") == 2


def test_fetchChapter_uses_override(tmp_path, monkeypatch):
    import core.clean as clean
    monkeypatch.setattr(clean, "_OVERRIDES_DIR", tmp_path / "overrides")
    # save override
    handle_rpc({"id": "1", "method": "saveSelectors", "params": {"url": _valid_url(), "start": ".custom"}})
    html = '<html><body><h1>Title</h1><div id="chapter-content">default</div><div class="custom">custom text</div></body></html>'
    mock_resp = Mock()
    mock_resp.text = html
    mock_resp.headers = {}
    mock_resp.status_code = 200
    with patch("adapters._http.requests.get", return_value=mock_resp):
        from adapters.novelphoenix import NovelPhoenixAdapter
        adapter = NovelPhoenixAdapter()
        cc = adapter.fetchChapter(_valid_url())
        assert "custom text" in cc.text
        assert "default" not in cc.text
    # clear
    handle_rpc({"id": "2", "method": "clearSelectors", "params": {"url": _valid_url()}})

def test_raw_not_filtered_invariant(tmp_path, monkeypatch):
    import core.clean as clean
    monkeypatch.setattr(clean, "_OVERRIDES_DIR", tmp_path / "overrides")
    raw = '<html><body><div id="chapter-content"><p>Keep</p><nav>nav</nav></div></body></html>'
    with patch("core.fetch.read_cache", return_value=raw):
        r = handle_rpc({"id": "1", "method": "previewChapter", "params": {"url": _valid_url(), "start": "div#chapter-content"}})
        assert "nav" not in r["result"]["text"]
        assert "nav" in r["result"]["originalHtml"]
