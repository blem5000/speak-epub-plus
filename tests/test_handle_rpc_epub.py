"""Tests for handle_rpc buildEpub — Story 2.4."""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, Mock

import pytest

from core.config import handle_rpc, _CHAPTER_CACHE, _normalize_cache_key
from core.ports import ChapterInfo


def _setup_chapter_cache(novel_url, n=5):
    _CHAPTER_CACHE.clear()
    key = _normalize_cache_key(novel_url)
    _CHAPTER_CACHE[key] = [{"index": i, "title": f"Chapter {i}", "url": f"{novel_url}/chapter/{i}"} for i in range(1, n + 1)]
    return key


def test_buildEpub_value_error_invalid_url():
    res = handle_rpc({"id": "1", "method": "buildEpub", "params": {"novelUrl": "not-url"}})
    assert res["error"]["code"] == "VALUE_ERROR"
    res2 = handle_rpc({"id": "2", "method": "buildEpub", "params": {"novelUrl": ""}})
    assert res2["error"]["code"] == "VALUE_ERROR"
    res3 = handle_rpc({"id": "3", "method": "buildEpub", "params": {"novelUrl": "ftp://evil.com/1"}})
    assert res3["error"]["code"] == "VALUE_ERROR"


def test_buildEpub_unsupported_host():
    res = handle_rpc({"id": "1", "method": "buildEpub", "params": {"novelUrl": "https://evil.com/novel/123"}})
    assert res["error"]["code"] == "LIST_FAILED"


def test_buildEpub_cache_miss(tmp_path, monkeypatch):
    novel_url = "https://www.novelphoenix.com/novel/123"
    _setup_chapter_cache(novel_url, n=5)
    # mock read_cache to miss for chapter 2
    def fake_read(url, cache_dir=None):
        if url.endswith("/2"):
            return None
        return '<html><body><div id="chapter-content"><p>hi</p></div></body></html>'
    with patch("core.fetch.read_cache", side_effect=fake_read):
        res = handle_rpc({"id": "1", "method": "buildEpub", "params": {"novelUrl": novel_url, "from": 1, "to": 3, "title": "Test", "outputDir": str(tmp_path / "out")}})
        assert res["error"]["code"] == "CACHE_MISS"
        assert "missing" in res["error"]
        assert any("/2" in m for m in res["error"]["missing"])
    _CHAPTER_CACHE.clear()


def test_buildEpub_clamp(tmp_path):
    novel_url = "https://www.novelphoenix.com/novel/123"
    _setup_chapter_cache(novel_url, n=10)
    def fake_read(url, cache_dir=None):
        return '<html><body><div id="chapter-content"><p>hi</p></div></body></html>'
    with patch("core.fetch.read_cache", side_effect=fake_read), patch("core.fetch.get_cache_path", side_effect=lambda u,c=None: Path("dummy")):
        # also need to mock epub building to avoid heavy? but we can let it build 10 chapters
        with patch("core.epub.build_epub") as mock_build:
            mock_build.return_value = {"path": str(tmp_path / "out" / "Test_chapters_001_to_010.epub"), "size": 12345, "chapter_count": 10, "epubcheck_ok": True, "messages": [], "logs": ["clamped 0->1, 999->10"], "from": 1, "to": 10}
            res = handle_rpc({"id": "1", "method": "buildEpub", "params": {"novelUrl": novel_url, "from": 0, "to": 999, "title": "Test", "outputDir": str(tmp_path / "out")}})
            # Should clamp to 1..10 and log
            assert "result" in res
            assert mock_build.called
            # check that build called with clamped from/to
            call_kwargs = mock_build.call_args[1]
            assert call_kwargs["from_idx"] == 1
            assert call_kwargs["to_idx"] == 10
    _CHAPTER_CACHE.clear()


def test_buildEpub_success_with_cover_and_filters(tmp_path):
    novel_url = "https://www.novelphoenix.com/novel/123"
    _setup_chapter_cache(novel_url, n=3)
    def fake_read(url, cache_dir=None):
        return '<html><body><div id="chapter-content"><p>Keep</p><p>Subscribe</p></div></body></html>'
    import core.config as cfg
    def fake_store_path():
        return tmp_path / "store.json"
    mock_resp = Mock()
    mock_resp.status_code = 200
    mock_resp.content = b"fakeimage"
    mock_resp.headers = {"Content-Type": "image/jpeg"}
    with patch.object(cfg, "get_store_path", fake_store_path):
        cfg.save_store({"filters": [{"pattern": "Subscribe", "isRegex": False}], "keepEPUB": True})
        with patch("core.fetch.read_cache", side_effect=fake_read), patch("core.fetch.get_cache_path", side_effect=lambda u, c=None: Path("dummy")), patch("requests.get", return_value=mock_resp):
            out = tmp_path / "output2"
            res = handle_rpc({"id": "2", "method": "buildEpub", "params": {"novelUrl": novel_url, "from": 1, "to": 3, "title": "Lord", "author": "Auth", "coverUrl": "https://example.com/cover.jpg", "outputDir": str(out)}})
            assert "result" in res, res
            assert Path(res["result"]["path"]).exists()
            assert res["result"]["chapter_count"] == 3
            assert res["result"]["epubcheck_ok"] is True
    _CHAPTER_CACHE.clear()
    try:
        (tmp_path / "store.json").unlink(missing_ok=True)
    except:
        pass


def test_buildEpub_epubcheck_proxy_when_missing(tmp_path):
    novel_url = "https://www.novelphoenix.com/novel/123"
    _setup_chapter_cache(novel_url, n=1)
    def fake_read(url, cache_dir=None):
        return '<html><body><div id="chapter-content"><p>hi</p></div></body></html>'
    import core.config as cfg
    def fake_store_path():
        return tmp_path / "store.json"
    with patch.object(cfg, "get_store_path", fake_store_path):
        cfg.save_store({"filters": []})
        with patch("core.fetch.read_cache", side_effect=fake_read), patch("core.fetch.get_cache_path", side_effect=lambda u,c=None: Path("dummy")), patch("shutil.which", return_value=None):
            out = tmp_path / "output_proxy"
            res = handle_rpc({"id": "1", "method": "buildEpub", "params": {"novelUrl": novel_url, "from": 1, "to": 1, "title": "Test", "outputDir": str(out)}})
            assert "result" in res
            assert any("proxy" in m.lower() for m in res["result"]["messages"])
    _CHAPTER_CACHE.clear()


def test_buildEpub_atomic_output_via_tmp(tmp_path):
    novel_url = "https://www.novelphoenix.com/novel/123"
    _setup_chapter_cache(novel_url, n=2)
    def fake_read(url, cache_dir=None):
        return '<html><body><div id="chapter-content"><p>hi</p></div></body></html>'
    import core.config as cfg
    def fake_store_path():
        return tmp_path / "store.json"
    with patch.object(cfg, "get_store_path", fake_store_path):
        cfg.save_store({"filters": []})
        out = tmp_path / "output_atomic"
        with patch("core.fetch.read_cache", side_effect=fake_read), patch("core.fetch.get_cache_path", side_effect=lambda u,c=None: Path("dummy")):
            res = handle_rpc({"id": "1", "method": "buildEpub", "params": {"novelUrl": novel_url, "from": 1, "to": 2, "title": "Test", "outputDir": str(out)}})
            assert "result" in res
            p = Path(res["result"]["path"])
            assert p.exists()
            # tmp should not exist
            assert not p.with_suffix(p.suffix + ".tmp").exists()
    _CHAPTER_CACHE.clear()


def test_buildEpub_keepEpub_reflection(tmp_path):
    novel_url = "https://www.novelphoenix.com/novel/123"
    _setup_chapter_cache(novel_url, n=1)
    def fake_read(url, cache_dir=None):
        return '<html><body><div id="chapter-content"><p>hi</p></div></body></html>'
    import core.config as cfg
    def fake_store_path():
        return tmp_path / "store.json"
    with patch.object(cfg, "get_store_path", fake_store_path):
        cfg.save_store({"filters": [], "keepEPUB": False})
        out = tmp_path / "output_keep"
        with patch("core.fetch.read_cache", side_effect=fake_read), patch("core.fetch.get_cache_path", side_effect=lambda u,c=None: Path("dummy")):
            res = handle_rpc({"id": "1", "method": "buildEpub", "params": {"novelUrl": novel_url, "from": 1, "to": 1, "title": "Test", "outputDir": str(out)}})
            assert "result" in res
            assert res["result"]["keepEPUB"] is False
            # file still written even though keepEPUB false (no deletion yet per Epic 4 keeps)
            assert Path(res["result"]["path"]).exists()
        # toggle true
        cfg.save_store({"keepEPUB": True})
        with patch("core.fetch.read_cache", side_effect=fake_read), patch("core.fetch.get_cache_path", side_effect=lambda u,c=None: Path("dummy")):
            res2 = handle_rpc({"id": "2", "method": "buildEpub", "params": {"novelUrl": novel_url, "from": 1, "to": 1, "title": "Test", "outputDir": str(out)}})
            assert res2["result"]["keepEPUB"] is True
    _CHAPTER_CACHE.clear()


def test_buildEpub_offline_no_network(tmp_path):
    novel_url = "https://www.novelphoenix.com/novel/123"
    _setup_chapter_cache(novel_url, n=2)
    def fake_read(url, cache_dir=None):
        return '<html><body><div id="chapter-content"><p>hi</p></div></body></html>'
    import core.config as cfg
    def fake_store_path():
        return tmp_path / "store.json"
    with patch.object(cfg, "get_store_path", fake_store_path):
        cfg.save_store({"filters": []})
        out = tmp_path / "output_offline"
        # Simulate offline: adapter.listChapters would fail if called, but we have cache so should not be called
        # Patch adapter to raise if called unexpectedly (should not be called because cache warm)
        with patch("adapters.novelphoenix.NovelPhoenixAdapter.listChapters", side_effect=Exception("offline")):
            with patch("core.fetch.read_cache", side_effect=fake_read), patch("core.fetch.get_cache_path", side_effect=lambda u,c=None: Path("dummy")), patch("requests.get", side_effect=Exception("offline")):
                res = handle_rpc({"id": "1", "method": "buildEpub", "params": {"novelUrl": novel_url, "from": 1, "to": 2, "title": "Test", "coverUrl": "https://example.com/cover.jpg", "outputDir": str(out)}})
                assert "result" in res
                # cover should be skipped but epub still valid
                assert Path(res["result"]["path"]).exists()
    _CHAPTER_CACHE.clear()


def test_getEpubStatus(tmp_path):
    # create dummy epub file
    out = tmp_path / "output_status"
    out.mkdir(parents=True)
    dummy = out / "Test_chapters_001_to_002.epub"
    dummy.write_bytes(b"fake epub content")
    import core.config as cfg
    def fake_store_path():
        return tmp_path / "store.json"
    with patch.object(cfg, "get_store_path", fake_store_path):
        res = handle_rpc({"id": "1", "method": "getEpubStatus", "params": {"outputDir": str(out)}})
        assert "result" in res
        assert res["result"]["exists"] is True
        assert res["result"]["path"] == str(dummy)
