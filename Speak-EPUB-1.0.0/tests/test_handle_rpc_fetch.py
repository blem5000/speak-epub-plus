"""Verification for handle_rpc fetchChapter(s) + getCacheStatus (2.1)."""
import sys
from pathlib import Path
from unittest.mock import Mock, patch
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PARENT = ROOT.parent
if str(PARENT) not in sys.path:
    sys.path.insert(0, str(PARENT))

from core.config import handle_rpc
from core.ports import ChapterContent, ChapterInfo


def _cc(url, title="Title", html="<div>html</div>", text="text"):
    return ChapterContent(url=url, title=title, html=html, text=text)


class TestFetchChapterRpc:
    def test_value_error_empty(self):
        res = handle_rpc({"id": "1", "method": "fetchChapter", "params": {"url": ""}})
        assert res["id"] == "1"
        assert res["error"]["code"] == "VALUE_ERROR"

    def test_value_error_ftp(self):
        res = handle_rpc({"id": "1", "method": "fetchChapter", "params": {"url": "ftp://evil.com/1"}})
        assert res["error"]["code"] == "VALUE_ERROR"

    def test_value_error_no_host(self):
        res = handle_rpc({"id": "1", "method": "fetchChapter", "params": {"url": "https://"}})
        assert res["error"]["code"] == "VALUE_ERROR"

    def test_list_failed_unsupported_host(self):
        res = handle_rpc({"id": "1", "method": "fetchChapter", "params": {"url": "https://evil.com/novel/123/chapter/1"}})
        assert res["error"]["code"] == "LIST_FAILED"
        assert "unsupported host" in res["error"]["message"]

    def test_import_failed(self):
        with patch("importlib.import_module", side_effect=ImportError("no mod")):
            res = handle_rpc({"id": "1", "method": "fetchChapter", "params": {"url": "https://www.novelphoenix.com/novel/123/chapter/1"}})
            assert res["error"]["code"] == "IMPORT_FAILED"

    @patch("adapters.novelphoenix.NovelPhoenixAdapter")
    def test_fetchChapter_success_serializes(self, MockAdapter):
        mock_inst = MockAdapter.return_value
        mock_inst.fetchChapter.return_value = _cc("https://www.novelphoenix.com/novel/123/chapter/1", title="Ch1", html="<div>hello</div>", text="hello")
        mock_inst._last_cover_url = "https://www.novelphoenix.com/covers/cover.jpg"
        # need to patch core.fetch.fetch_one to avoid cache and sleep? Actually handle_rpc uses fetch_one which will check cache and then call adapter
        # Mock fetch_one to just call adapter directly for speed?
        # We patch time.sleep and random to avoid delay, and ensure cache miss
        with patch("core.fetch.read_cache", return_value=None), patch("core.fetch.write_cache"), patch("core.fetch.time.sleep", return_value=None), patch("core.fetch.random.uniform", return_value=0.3):
            res = handle_rpc({"id": "1", "method": "fetchChapter", "params": {"url": "https://www.novelphoenix.com/novel/123/chapter/1"}})
        assert "result" in res
        assert res["result"]["title"] == "Ch1"
        assert res["result"]["html"] == "<div>hello</div>"
        assert res["result"]["text"] == "hello"
        assert res["result"]["url"] == "https://www.novelphoenix.com/novel/123/chapter/1"
        assert res["result"]["cover_url"] == "https://www.novelphoenix.com/covers/cover.jpg"

    @patch("adapters.novelphoenix.NovelPhoenixAdapter")
    def test_fetchChapter_cover_fallback_none(self, MockAdapter):
        mock_inst = MockAdapter.return_value
        mock_inst.fetchChapter.return_value = _cc("https://www.novelphoenix.com/novel/123/chapter/1")
        mock_inst._last_cover_url = None
        with patch("core.fetch.read_cache", return_value=None), patch("core.fetch.write_cache"), patch("core.fetch.time.sleep", return_value=None), patch("core.fetch.random.uniform", return_value=0.3):
            res = handle_rpc({"id": "1", "method": "fetchChapter", "params": {"url": "https://www.novelphoenix.com/novel/123/chapter/1"}})
        assert "result" in res
        # cover_url None fallback
        assert res["result"]["cover_url"] is None

    @patch("adapters.novelphoenix.NovelPhoenixAdapter")
    def test_fetchChapter_adapter_non_list_LIST_FAILED(self, MockAdapter):
        mock_inst = MockAdapter.return_value
        mock_inst.fetchChapter.return_value = None
        with patch("core.fetch.read_cache", return_value=None), patch("core.fetch.write_cache"), patch("core.fetch.time.sleep", return_value=None), patch("core.fetch.random.uniform", return_value=0.3):
            res = handle_rpc({"id": "1", "method": "fetchChapter", "params": {"url": "https://www.novelphoenix.com/novel/123/chapter/1"}})
        assert res["error"]["code"] == "LIST_FAILED"

    @patch("adapters.novelphoenix.NovelPhoenixAdapter")
    def test_fetchChapter_403_maps_LIST_FAILED(self, MockAdapter):
        from core.ports import AdapterError
        mock_inst = MockAdapter.return_value
        mock_inst.fetchChapter.side_effect = AdapterError("403 Forbidden", code="LIST_FAILED")
        with patch("core.fetch.read_cache", return_value=None), patch("core.fetch.write_cache"), patch("core.fetch.time.sleep", return_value=None), patch("core.fetch.random.uniform", return_value=0.3):
            # fetch_one will retry 5 times then raise LIST_FAILED
            res = handle_rpc({"id": "1", "method": "fetchChapter", "params": {"url": "https://www.novelphoenix.com/novel/123/chapter/1"}})
        assert res["error"]["code"] == "LIST_FAILED"


class TestFetchChaptersRpc:
    def test_value_error_empty_urls(self):
        res = handle_rpc({"id": "1", "method": "fetchChapters", "params": {"urls": [""]}})
        assert res["error"]["code"] == "VALUE_ERROR"

    def test_list_failed_unsupported_batch(self):
        res = handle_rpc({"id": "1", "method": "fetchChapters", "params": {"urls": ["https://evil.com/novel/123/chapter/1"]}})
        assert res["error"]["code"] == "LIST_FAILED"

    def test_import_failed_batch(self):
        with patch("importlib.import_module", side_effect=ImportError("no mod")):
            res = handle_rpc({"id": "1", "method": "fetchChapters", "params": {"urls": ["https://www.novelphoenix.com/novel/123/chapter/1"]}})
            assert res["error"]["code"] == "IMPORT_FAILED"

    @patch("adapters.novelphoenix.NovelPhoenixAdapter")
    def test_fetchChapters_batch_20_100_skip_cached(self, MockAdapter, tmp_path, monkeypatch):
        # Setup cache via patching CACHE_ROOT
        import core.fetch as fetch_mod
        monkeypatch.setattr(fetch_mod, "CACHE_ROOT", tmp_path)
        # Prepopulate 1-20 cache
        for i in range(1, 21):
            url = f"https://www.novelphoenix.com/novel/123/chapter/{i}"
            p = fetch_mod.get_cache_path(url)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f"<div>cached {i}</div>", encoding="utf-8")
        mock_inst = MockAdapter.return_value
        # fetchChapter for missing 21-100
        def fetch_side(url):
            return _cc(url, title=f"Title {url.split('/')[-1]}", html=f"<div>{url}</div>", text="text")
        mock_inst.fetchChapter.side_effect = fetch_side
        mock_inst._last_cover_url = None
        mock_inst.listChapters.return_value = []  # not used
        urls = [f"https://www.novelphoenix.com/novel/123/chapter/{i}" for i in range(1, 101)]
        # Also need to handle novelUrl maybe? We'll pass novelUrl for range
        with patch("core.fetch.time.sleep", return_value=None), patch("core.fetch.random.uniform", return_value=0.3):
            res = handle_rpc({"id": "1", "method": "fetchChapters", "params": {"urls": urls, "novelUrl": "https://www.novelphoenix.com/novel/123", "from": 1, "to": 100}})
        assert "result" in res
        result = res["result"]
        assert result["skipped"] == 20
        assert len(result["chapters"]) == 80  # 21-100
        assert result["badge"] and "pominięto 20" in result["badge"]
        assert any("pominięto" in l for l in result["logs"])
        # Verify only 80 fetches (21-100)
        assert mock_inst.fetchChapter.call_count == 80

    @patch("adapters.novelphoenix.NovelPhoenixAdapter")
    def test_fetchChapters_open_ended_revalidate(self, MockAdapter, tmp_path, monkeypatch):
        import core.fetch as fetch_mod
        monkeypatch.setattr(fetch_mod, "CACHE_ROOT", tmp_path)
        # cache 1-100
        for i in range(1, 101):
            url = f"https://www.novelphoenix.com/novel/123/chapter/{i}"
            p = fetch_mod.get_cache_path(url)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f"<div>{i}</div>", encoding="utf-8")
        novel_url = "https://www.novelphoenix.com/novel/123"
        fresh = [ChapterInfo(index=i, title=f"Chapter {i}", url=f"https://www.novelphoenix.com/novel/123/chapter/{i}") for i in range(1, 143)]
        mock_inst = MockAdapter.return_value
        mock_inst.listChapters.return_value = fresh
        mock_inst.fetchChapter.side_effect = lambda url: _cc(url)
        mock_inst._last_cover_url = None
        with patch("core.fetch.time.sleep", return_value=None), patch("core.fetch.random.uniform", return_value=0.3):
            res = handle_rpc({"id": "1", "method": "fetchChapters", "params": {"novelUrl": novel_url, "from": 1, "to": None}})
        assert "result" in res
        result = res["result"]
        assert result["skipped"] == 100
        assert result["total"] == 142
        assert len(result["chapters"]) == 42
        assert "wykryto 42 nowe" in result["badge"]
        mock_inst.listChapters.assert_called_with(novel_url)

    @patch("adapters.novelphoenix.NovelPhoenixAdapter")
    def test_getCacheStatus(self, MockAdapter, tmp_path, monkeypatch):
        import core.fetch as fetch_mod
        monkeypatch.setattr(fetch_mod, "CACHE_ROOT", tmp_path)
        for i in range(1, 6):
            url = f"https://www.novelphoenix.com/novel/123/chapter/{i}"
            p = fetch_mod.get_cache_path(url)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x", encoding="utf-8")
        urls = [f"https://www.novelphoenix.com/novel/123/chapter/{i}" for i in range(1, 11)]
        res = handle_rpc({"id": "1", "method": "getCacheStatus", "params": {"urls": urls}})
        assert "result" in res
        assert res["result"]["total"] == 10
        assert res["result"]["skipped"] == 5
        assert res["result"]["missing"] == 5
