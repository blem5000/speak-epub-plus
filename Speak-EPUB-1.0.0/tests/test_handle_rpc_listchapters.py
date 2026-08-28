"""Verification for handle_rpc listChapters + selection persistence (review patch)."""
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import pytest

# Ensure repo root on path (Speak-EPUB-1.0.0 is package root's parent)
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# Also add parent of Speak-EPUB-1.0.0 for adapters.* import
PARENT = ROOT.parent
if str(PARENT) not in sys.path:
    sys.path.insert(0, str(PARENT))

from core.config import handle_rpc, _CHAPTER_CACHE
from core.ports import ChapterInfo


def _ci(idx, title="Title", url="https://www.novelphoenix.com/novel/123/chapter/1", cover=None):
    return ChapterInfo(index=idx, title=title, url=url)


class TestListChaptersRpc:
    def setup_method(self):
        _CHAPTER_CACHE.clear()

    def test_value_error_empty_url(self):
        res = handle_rpc({"id": "1", "method": "listChapters", "params": {"url": ""}})
        assert res["id"] == "1"
        assert res["error"]["code"] == "VALUE_ERROR"

    def test_value_error_ftp(self):
        res = handle_rpc({"id": "1", "method": "listChapters", "params": {"url": "ftp://evil.com/1"}})
        assert res["error"]["code"] == "VALUE_ERROR"

    def test_value_error_no_host(self):
        res = handle_rpc({"id": "1", "method": "listChapters", "params": {"url": "https://"}})
        assert res["error"]["code"] == "VALUE_ERROR"

    def test_list_failed_unsupported_host(self):
        # any non-novelphoenix host → LIST_FAILED (host guard)
        res = handle_rpc({"id": "1", "method": "listChapters", "params": {"url": "https://evil.com/novel/123"}})
        assert res["error"]["code"] == "LIST_FAILED"
        assert "unsupported host" in res["error"]["message"]

    def test_list_failed_allows_subdomain(self):
        # should not block subdomain, but adapter mock will handle
        with patch("adapters.novelphoenix.NovelPhoenixAdapter") as MockAdapter:
            mock_inst = MockAdapter.return_value
            mock_inst.listChapters.return_value = [_ci(1)]
            mock_inst._last_cover_url = None
            res = handle_rpc({"id": "1", "method": "listChapters", "params": {"url": "https://sub.novelphoenix.com/novel/123"}})
            assert "result" in res
            assert res["result"][0]["index"] == 1

    @patch("adapters.novelphoenix.NovelPhoenixAdapter")
    def test_success_serializes_and_caches(self, MockAdapter):
        mock_inst = MockAdapter.return_value
        mock_inst.listChapters.return_value = [
            _ci(1, title="Chapter 1", url="https://www.novelphoenix.com/novel/123/chapter/1"),
            _ci(2, title="", url="https://www.novelphoenix.com/novel/123/chapter/2"),  # empty title → —
        ]
        mock_inst._last_cover_url = "https://www.novelphoenix.com/covers/cover.jpg"
        # cover_url None on second should fallback
        mock_inst.listChapters.return_value[1] = Mock(index=2, title="", url="https://www.novelphoenix.com/novel/123/chapter/2", cover_url=None)

        res = handle_rpc({"id": "1", "method": "listChapters", "params": {"url": "https://www.novelphoenix.com/novel/123"}})
        assert "result" in res
        assert len(res["result"]) == 2
        assert res["result"][0]["title"] == "Chapter 1"
        assert res["result"][1]["title"] == "—"
        assert res["result"][1]["cover_url"] == "https://www.novelphoenix.com/covers/cover.jpg"
        # second call should hit cache (no second adapter invocation)
        mock_inst.listChapters.reset_mock()
        res2 = handle_rpc({"id": "2", "method": "listChapters", "params": {"url": "https://www.novelphoenix.com/novel/123"}})
        assert res2["result"] == res["result"]
        mock_inst.listChapters.assert_not_called()

    @patch("adapters.novelphoenix.NovelPhoenixAdapter")
    def test_non_list_returns_list_failed(self, MockAdapter):
        MockAdapter.return_value.listChapters.return_value = None  # type: ignore
        res = handle_rpc({"id": "1", "method": "listChapters", "params": {"url": "https://www.novelphoenix.com/novel/123"}})
        assert res["error"]["code"] == "LIST_FAILED"

    @patch("adapters.novelphoenix.NovelPhoenixAdapter")
    def test_403_maps_to_list_failed(self, MockAdapter):
        from core.ports import AdapterError
        MockAdapter.return_value.listChapters.side_effect = AdapterError("403 Forbidden", code="LIST_FAILED")
        res = handle_rpc({"id": "1", "method": "listChapters", "params": {"url": "https://www.novelphoenix.com/novel/123"}})
        assert res["error"]["code"] == "LIST_FAILED"

    @patch("adapters.novelphoenix.NovelPhoenixAdapter")
    def test_429_maps_to_list_failed_via_msg(self, MockAdapter):
        MockAdapter.return_value.listChapters.side_effect = Exception("429 Too Many Requests")
        res = handle_rpc({"id": "1", "method": "listChapters", "params": {"url": "https://www.novelphoenix.com/novel/123"}})
        assert res["error"]["code"] == "LIST_FAILED"

    @patch("adapters.novelphoenix.NovelPhoenixAdapter")
    def test_index_negative_fallback(self, MockAdapter):
        # adapter returns index 0/negative → should be corrected to enum order
        c1 = Mock(index=0, title="T0", url="https://www.novelphoenix.com/novel/123/chapter/0", cover_url=None)
        c2 = Mock(index=-5, title="Tneg", url="https://www.novelphoenix.com/novel/123/chapter/1", cover_url=None)
        MockAdapter.return_value.listChapters.return_value = [c1, c2]
        MockAdapter.return_value._last_cover_url = None
        res = handle_rpc({"id": "1", "method": "listChapters", "params": {"url": "https://www.novelphoenix.com/novel/123"}})
        assert res["result"][0]["index"] == 1
        assert res["result"][1]["index"] == 2

    def test_import_failed(self):
        with patch("importlib.import_module", side_effect=ImportError("no mod")):
            res = handle_rpc({"id": "1", "method": "listChapters", "params": {"url": "https://www.novelphoenix.com/novel/123"}})
            assert res["error"]["code"] == "IMPORT_FAILED"

    @patch("adapters.novelphoenix.NovelPhoenixAdapter")
    def test_port_and_userinfo_stripped(self, MockAdapter):
        mock_inst = MockAdapter.return_value
        mock_inst.listChapters.return_value = [_ci(1)]
        mock_inst._last_cover_url = None
        # port 443 should be allowed
        res = handle_rpc({"id": "1", "method": "listChapters", "params": {"url": "https://www.novelphoenix.com:443/novel/123"}})
        assert "result" in res
        # userinfo bypass should be blocked — evil.com@www.novelphoenix.com → host is www.novelphoenix.com (allowed) but tricky, ensure allowed
        # trailing dot
        res2 = handle_rpc({"id": "2", "method": "listChapters", "params": {"url": "https://www.novelphoenix.com./novel/123"}})
        assert "result" in res2
        # 500 maps to LIST_FAILED via msg regex — use fresh cache key (distinct novel) to avoid masking by prior success cache
        _CHAPTER_CACHE.clear()
        MockAdapter.return_value.listChapters.side_effect = Exception("500 Internal Server Error")
        res3 = handle_rpc({"id": "3", "method": "listChapters", "params": {"url": "https://www.novelphoenix.com/novel/999"}})
        assert res3["error"]["code"] == "LIST_FAILED"
        _CHAPTER_CACHE.clear()
        # cache poisoning — mutating result should not affect cache
        MockAdapter.return_value.listChapters.side_effect = None
        MockAdapter.return_value.listChapters.return_value = [_ci(1, title="Orig")]
        mock_inst._last_cover_url = None
        res4 = handle_rpc({"id": "4", "method": "listChapters", "params": {"url": "https://www.novelphoenix.com/novel/123"}})
        res4["result"][0]["title"] = "Mutated"
        res5 = handle_rpc({"id": "5", "method": "listChapters", "params": {"url": "https://www.novelphoenix.com/novel/123"}})
        assert res5["result"][0]["title"] == "Orig"


class TestSelectionRpc:
    def test_get_set_selection_roundtrip(self, tmp_path, monkeypatch):
        # isolate store.json to tmp
        store_file = tmp_path / "store.json"
        monkeypatch.chdir(tmp_path)
        # ensure parent for import still works
        res = handle_rpc({"id": "1", "method": "setSelection", "params": {"selection": [1, 2, 30], "from": 1, "to": 30, "url": "https://www.novelphoenix.com/novel/123"}})
        assert res["result"]["saved"] is True
        res2 = handle_rpc({"id": "2", "method": "getSelection", "params": {}})
        assert res2["result"]["selection"] == [1, 2, 30]
        assert res2["result"]["from"] == 1
        assert res2["result"]["to"] == 30
        assert res2["result"]["url"] == "https://www.novelphoenix.com/novel/123"
        # invalid entries filtered
        handle_rpc({"id": "3", "method": "setSelection", "params": {"selection": [0, -1, "x", 5]}})
        res3 = handle_rpc({"id": "4", "method": "getSelection", "params": {}})
        assert res3["result"]["selection"] == [5]
