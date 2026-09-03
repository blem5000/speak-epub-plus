"""Tests for NovelPhoenixAdapter + aggregator (Epic 1.2).

Mocked requests.get fixtures cover:
- search 2 results (142 + None)
- listChapters 142+3 noise ordered/dedupe
- cover og:image vs fallback
- empty → []
- selectors non-empty
- aggregator dedupe + fault isolation + timeout
- validation edge cases
"""
import time
import re
from unittest.mock import Mock, patch, MagicMock

# Save original sleep before any patching of adapters._http.time.sleep (which patches time.sleep globally)
_real_sleep = time.sleep

import pytest
import requests

from adapters.base import guess_adapter
from adapters.novelphoenix import NovelPhoenixAdapter
from core.aggregator import search_all
from core.ports import AdapterError, ScraperPort, SearchResult, Selectors


# ------------------------------------------------------------------ helpers
def _mock_response(text: str, status_code: int = 200, url: str = "https://www.novelphoenix.com/search?keyword=test"):
    m = Mock()
    m.status_code = status_code
    m.text = text
    m.url = url
    m.headers = {}
    # raise_for_status behavior
    def _raise():
        if status_code >= 400:
            err = requests.exceptions.HTTPError(f"{status_code} for {url}", response=m)
            raise err
    m.raise_for_status = _raise
    return m


SEARCH_HTML_2 = """
<html><body>
<div class="book-item">
  <a href="/novel/123-lord-of-mysteries">Lord of Mysteries</a>
  <span class="chapters">142 chapters</span>
  <img src="/covers/123.jpg"/>
</div>
<div class="book-item">
  <a href="https://www.novelphoenix.com/novel/456-other">Other Title</a>
  <!-- no chapters span -->
</div>
</body></html>
"""

SEARCH_HTML_EMPTY = "<html><body><div class='search-results'>no results</div></body></html>"

def _list_chapters_html(num=142, with_og=True, with_fallback=False, include_noise=True):
    parts = ["<html><head>"]
    if with_og:
        parts.append('<meta property="og:image" content="https://www.novelphoenix.com/covers/cover.jpg"/>')
    parts.append("</head><body>")
    if with_fallback and not with_og:
        parts.append('<img class="cover" src="/covers/fallback.jpg"/>')
    parts.append('<ul class="chapter-list">')
    for i in range(1, num + 1):
        parts.append(f'<li><a href="/novel/123/chapter/{i}">Chapter {i}: Title {i}</a></li>')
    if include_noise:
        # dupe
        parts.append('<li><a href="/novel/123/chapter/1">Chapter 1: Title 1</a></li>')
        # Next filtered
        parts.append('<li><a href="/novel/123/chapter/999">Next</a></li>')
        # empty
        parts.append('<li><a href="/novel/123/chapter/1000"></a></li>')
    parts.append("</ul></body></html>")
    return "".join(parts)

CHAPTER_HTML_SELECTOR = """
<html><body>
<h1>Chapter 1: Dawn</h1>
<div id="chapter-content"><p>Real chapter text.</p><script>alert('bad')</script><nav>nav chrome</nav><style>bad</style></div>
</body></html>
"""

CHAPTER_HTML_HEURISTIC = """
<html><body>
<article><p>Heuristic article text.</p><script>bad</script><style>bad</style></article>
</body></html>
"""


# ------------------------------------------------------------------ search
class TestSearch:
    @patch("adapters._http.requests.get")
    @patch("adapters._http.time.sleep", return_value=None)
    def test_search_returns_2_results(self, mock_sleep, mock_get):
        mock_get.return_value = _mock_response(SEARCH_HTML_2)
        adapter = NovelPhoenixAdapter()
        start = time.time()
        results = adapter.search("Lord of Mysteries")
        elapsed = time.time() - start
        assert elapsed < 5, "search should be <5s single-site"
        assert len(results) == 2
        r1, r2 = results
        # site
        assert r1.site == "novelphoenix.com"
        assert r2.site == "novelphoenix.com"
        # title non-empty
        assert r1.title == "Lord of Mysteries"
        assert r2.title == "Other Title"
        # url absolute via urljoin
        assert r1.url == "https://www.novelphoenix.com/novel/123-lord-of-mysteries"
        assert r2.url == "https://www.novelphoenix.com/novel/456-other"
        # chapter_count via regex (\d+) or None
        assert r1.chapter_count == 142
        assert r2.chapter_count is None
        # cover_url populated for first
        assert r1.cover_url == "https://www.novelphoenix.com/covers/123.jpg"
        # issubclass
        assert issubclass(NovelPhoenixAdapter, ScraperPort)

    @patch("adapters._http.requests.get")
    @patch("adapters._http.time.sleep", return_value=None)
    def test_search_empty_returns_empty(self, mock_sleep, mock_get):
        mock_get.return_value = _mock_response(SEARCH_HTML_EMPTY)
        adapter = NovelPhoenixAdapter()
        results = adapter.search("zzzz_no_match")
        assert results == []

    @patch("adapters._http.requests.get")
    def test_search_validation_empty_raises_without_network(self, mock_get):
        adapter = NovelPhoenixAdapter()
        with pytest.raises(ValueError):
            adapter.search("")
        with pytest.raises(ValueError):
            adapter.search("   ")
        # ValueError before network => no request
        mock_get.assert_not_called()

    @patch("adapters._http.requests.get")
    @patch("adapters._http.time.sleep", return_value=None)
    def test_search_truncates_long_title(self, mock_sleep, mock_get):
        mock_get.return_value = _mock_response(SEARCH_HTML_EMPTY)
        adapter = NovelPhoenixAdapter()
        long_title = "a" * 350
        adapter.search(long_title)
        # capture URL
        called_url = mock_get.call_args[0][0]
        # should be truncated to 200 before quote
        # extract keyword param
        from urllib.parse import urlparse, parse_qs, unquote
        qs = parse_qs(urlparse(called_url).query)
        kw = qs.get("keyword", [""])[0]
        decoded = unquote(kw)
        assert len(decoded) == 200
        assert decoded == "a" * 200

    @patch("adapters._http.requests.get")
    @patch("adapters._http.time.sleep", return_value=None)
    def test_search_handles_4xx_returns_empty_no_raise(self, mock_sleep, mock_get):
        # Simulate 500 error then retries -> final [] + log
        mock_resp = _mock_response("error", status_code=500)
        mock_get.return_value = mock_resp
        adapter = NovelPhoenixAdapter()
        # mock_get will be called 3 times (retries+1) via _get
        results = adapter.search("Lord of Mysteries")
        assert results == []
        # should have retried 3 times (initial +2 retries)
        assert mock_get.call_count == 3

    @patch("adapters._http.requests.get")
    @patch("adapters._http.time.sleep", return_value=None)
    def test_search_timeout_returns_empty(self, mock_sleep, mock_get):
        mock_get.side_effect = requests.exceptions.Timeout("timeout")
        adapter = NovelPhoenixAdapter()
        results = adapter.search("Lord of Mysteries")
        assert results == []
        assert mock_get.call_count == 3

    @patch("adapters._http.requests.get")
    @patch("adapters._http.time.sleep", return_value=None)
    def test_search_url_builds_correctly(self, mock_sleep, mock_get):
        mock_get.return_value = _mock_response(SEARCH_HTML_EMPTY)
        adapter = NovelPhoenixAdapter()
        adapter.search("hello world")
        called_url = mock_get.call_args[0][0]
        assert called_url.startswith("https://www.novelphoenix.com/search?keyword=")
        assert "hello%20world" in called_url or "hello" in called_url


# ------------------------------------------------------------------ listChapters
class TestListChapters:
    @patch("adapters._http.requests.get")
    @patch("adapters._http.time.sleep", return_value=None)
    def test_listChapters_142_ordered_deduped(self, mock_sleep, mock_get):
        html = _list_chapters_html(num=142, with_og=True, include_noise=True)
        mock_get.return_value = _mock_response(html, url="https://www.novelphoenix.com/novel/123")
        adapter = NovelPhoenixAdapter()
        results = adapter.listChapters("https://www.novelphoenix.com/novel/123")
        assert len(results) == 142, f"expected 142 got {len(results)}"
        # 1..N contiguous ordered
        for idx, ci in enumerate(results, 1):
            assert ci.index == idx
            assert ci.url.startswith("https://www.novelphoenix.com")
            assert ci.title.startswith("Chapter")
        # dedupe: first chapter url should appear once
        urls = [c.url for c in results]
        assert len(urls) == len(set(urls))
        # noise filtered: no Next, no empty
        titles = [c.title for c in results]
        assert "Next" not in titles
        assert "" not in titles
        # cover via og:image
        assert adapter._last_cover_url == "https://www.novelphoenix.com/covers/cover.jpg"
        # cover_url populated else None without failure - here populated
        assert adapter._last_cover_url is not None

    @patch("adapters._http.requests.get")
    @patch("adapters._http.time.sleep", return_value=None)
    def test_listChapters_cover_fallback(self, mock_sleep, mock_get):
        html = _list_chapters_html(num=5, with_og=False, with_fallback=True, include_noise=False)
        mock_get.return_value = _mock_response(html, url="https://www.novelphoenix.com/novel/123")
        adapter = NovelPhoenixAdapter()
        results = adapter.listChapters("https://www.novelphoenix.com/novel/123")
        assert len(results) == 5
        assert adapter._last_cover_url == "https://www.novelphoenix.com/covers/fallback.jpg"

    @patch("adapters._http.requests.get")
    @patch("adapters._http.time.sleep", return_value=None)
    def test_listChapters_no_cover(self, mock_sleep, mock_get):
        html = _list_chapters_html(num=3, with_og=False, with_fallback=False, include_noise=False)
        mock_get.return_value = _mock_response(html, url="https://www.novelphoenix.com/novel/123")
        adapter = NovelPhoenixAdapter()
        results = adapter.listChapters("https://www.novelphoenix.com/novel/123")
        assert len(results) == 3
        assert adapter._last_cover_url is None

    @patch("adapters._http.requests.get")
    @patch("adapters._http.time.sleep", return_value=None)
    def test_listChapters_empty_after_filter_returns_empty(self, mock_sleep, mock_get):
        html = '<html><head><meta property="og:image" content="https://example.com/c.jpg"/></head><body><ul class="chapter-list"><li><a href="/novel/1/chapter/999">Next</a></li><li><a href="/x"></a></li></ul></body></html>'
        mock_get.return_value = _mock_response(html, url="https://www.novelphoenix.com/novel/123")
        adapter = NovelPhoenixAdapter()
        results = adapter.listChapters("https://www.novelphoenix.com/novel/123")
        assert results == []

    @patch("adapters._http.requests.get")
    @patch("adapters._http.time.sleep", return_value=None)
    def test_listChapters_404_raises_AdapterError(self, mock_sleep, mock_get):
        mock_resp = _mock_response("not found", status_code=404, url="https://www.novelphoenix.com/novel/999")
        mock_get.return_value = mock_resp
        adapter = NovelPhoenixAdapter()
        with pytest.raises(AdapterError) as exc:
            adapter.listChapters("https://www.novelphoenix.com/novel/999")
        assert "LIST_FAILED" in str(exc.value) or exc.value.code == "LIST_FAILED"

    @patch("adapters._http.requests.get")
    @patch("adapters._http.time.sleep", return_value=None)
    def test_listChapters_timeout_raises(self, mock_sleep, mock_get):
        mock_get.side_effect = requests.exceptions.Timeout("timeout")
        adapter = NovelPhoenixAdapter()
        with pytest.raises(AdapterError):
            adapter.listChapters("https://www.novelphoenix.com/novel/123")

    @patch("adapters._http.requests.get")
    @patch("adapters._http.time.sleep", return_value=None)
    def test_listChapters_5xx_retries_then_raises(self, mock_sleep, mock_get):
        mock_resp = _mock_response("err", status_code=500)
        mock_get.return_value = mock_resp
        adapter = NovelPhoenixAdapter()
        with pytest.raises(AdapterError):
            adapter.listChapters("https://www.novelphoenix.com/novel/123")
        assert mock_get.call_count == 3

    @patch("adapters._http.requests.get")
    @patch("adapters._http.time.sleep", return_value=None)
    def test_listChapters_url_absolute_via_urljoin(self, mock_sleep, mock_get):
        html = '<html><body><ul class="chapter-list"><li><a href="/novel/123/chapter/1">Chapter 1</a></li></ul></body></html>'
        mock_get.return_value = _mock_response(html, url="https://www.novelphoenix.com/novel/123")
        adapter = NovelPhoenixAdapter()
        results = adapter.listChapters("https://www.novelphoenix.com/novel/123")
        assert results[0].url == "https://www.novelphoenix.com/novel/123/chapter/1"

    @patch("adapters._http.requests.get")
    @patch("adapters._http.time.sleep", return_value=None)
    def test_listChapters_fallback_selector_a_href_chapter(self, mock_sleep, mock_get):
        # No ul.chapter-list, but a[href*=/chapter/] present
        html = '<html><body><div class="content"><a href="https://www.novelphoenix.com/novel/123/chapter/1">Chapter 1</a><a href="https://www.novelphoenix.com/novel/123/chapter/2">Chapter 2</a></div></body></html>'
        mock_get.return_value = _mock_response(html, url="https://www.novelphoenix.com/novel/123")
        adapter = NovelPhoenixAdapter()
        results = adapter.listChapters("https://www.novelphoenix.com/novel/123")
        assert len(results) == 2


# ------------------------------------------------------------------ fetchChapter
class TestFetchChapter:
    @patch("adapters._http.requests.get")
    @patch("adapters._http.time.sleep", return_value=None)
    def test_fetchChapter_via_selector(self, mock_sleep, mock_get):
        mock_get.return_value = _mock_response(CHAPTER_HTML_SELECTOR, url="https://www.novelphoenix.com/novel/123/chapter/1")
        adapter = NovelPhoenixAdapter()
        cc = adapter.fetchChapter("https://www.novelphoenix.com/novel/123/chapter/1")
        assert cc.url == "https://www.novelphoenix.com/novel/123/chapter/1"
        assert "Real chapter text" in cc.text
        assert "alert" not in cc.text
        assert "nav chrome" not in cc.text
        assert "<script" not in cc.html

    @patch("adapters._http.requests.get")
    @patch("adapters._http.time.sleep", return_value=None)
    def test_fetchChapter_heuristic_fallback(self, mock_sleep, mock_get):
        mock_get.return_value = _mock_response(CHAPTER_HTML_HEURISTIC, url="https://www.novelphoenix.com/novel/123/chapter/2")
        adapter = NovelPhoenixAdapter()
        # force getSelectors to return None to test fallback
        with patch.object(adapter, "getSelectors", return_value=Selectors(start=None, end=None)):
            cc = adapter.fetchChapter("https://www.novelphoenix.com/novel/123/chapter/2")
            assert "Heuristic article text" in cc.text
            assert "bad" not in cc.text

    @patch("adapters._http.requests.get")
    @patch("adapters._http.time.sleep", return_value=None)
    def test_fetchChapter_404_raises(self, mock_sleep, mock_get):
        mock_resp = _mock_response("not found", status_code=404, url="https://www.novelphoenix.com/novel/123/chapter/999")
        mock_get.return_value = mock_resp
        adapter = NovelPhoenixAdapter()
        with pytest.raises(AdapterError) as exc:
            adapter.fetchChapter("https://www.novelphoenix.com/novel/123/chapter/999")
        assert exc.value.code in ("LIST_FAILED", "FETCH_FAILED")

    @patch("adapters._http.requests.get")
    @patch("adapters._http.time.sleep", return_value=None)
    def test_fetchChapter_captures_cover(self, mock_sleep, mock_get):
        html = (
            '<html><head><meta property="og:image" content="/covers/123.jpg"/></head><body>'
            "<h1>Chapter 1</h1>"
            '<div id="chapter-content"><p>Text.</p></div>'
            "</body></html>"
        )
        mock_get.return_value = _mock_response(html, url="https://www.novelphoenix.com/novel/123/chapter/1")
        adapter = NovelPhoenixAdapter()
        cc = adapter.fetchChapter("https://www.novelphoenix.com/novel/123/chapter/1")
        assert adapter._last_cover_url == "https://www.novelphoenix.com/covers/123.jpg"
        assert cc.cover_url == "https://www.novelphoenix.com/covers/123.jpg"


# ------------------------------------------------------------------ getSelectors
class TestSelectors:
    def test_getSelectors_non_empty(self):
        adapter = NovelPhoenixAdapter()
        sel = adapter.getSelectors()
        assert isinstance(sel, Selectors)
        assert sel.start == "div#chapter-content"
        assert sel.end is None
        # never "" (ports normalizes)
        assert sel.start != ""
        assert sel.end != ""

    def test_selectors_normalizes_empty(self):
        s = Selectors(start="", end="")
        assert s.start is None
        assert s.end is None


# ------------------------------------------------------------------ guess_adapter
class TestGuessAdapter:
    def test_guess_novelphoenix(self):
        assert guess_adapter("https://www.novelphoenix.com/book/123") == "novelphoenix"
        assert guess_adapter("https://novelphoenix.com/novel/abc") == "novelphoenix"

    def test_guess_spoof_query_param(self):
        assert guess_adapter("https://evil.com?x=novelphoenix.com") is None
        assert guess_adapter("https://evil.com?novelphoenix.com=1") is None
        assert guess_adapter("https://evil.com#novelphoenix.com") is None

    def test_guess_subdomain(self):
        assert guess_adapter("https://sub.novelphoenix.com/novel/123") == "novelphoenix"


# ------------------------------------------------------------------ aggregator
class TestAggregator:
    @patch("adapters._http.time.sleep", return_value=None)
    def test_search_all_dedupe_and_fault_isolate(self, mock_sleep):
        # two adapters: one slow (0.8s), one fast (0.2s) + one raising
        class FastAdapter(ScraperPort):
            def search(self, title: str):
                _real_sleep(0.2)
                return [SearchResult(site="novelphoenix.com", title="A", url="https://www.novelphoenix.com/novel/1", chapter_count=10)]
            def listChapters(self, url: str): return []
            def fetchChapter(self, url: str): raise NotImplementedError
            def getSelectors(self): return Selectors(start=None, end=None)

        class SlowAdapter(ScraperPort):
            def search(self, title: str):
                _real_sleep(0.8)
                return [SearchResult(site="novelphoenix.com", title="A", url="https://www.novelphoenix.com/novel/1", chapter_count=10),
                        SearchResult(site="novelphoenix.com", title="B", url="https://www.novelphoenix.com/novel/2", chapter_count=5)]
            def listChapters(self, url: str): return []
            def fetchChapter(self, url: str): raise NotImplementedError
            def getSelectors(self): return Selectors(start=None, end=None)

        class FailingAdapter(ScraperPort):
            def search(self, title: str):
                raise AdapterError("fail", code="LIST_FAILED")
            def listChapters(self, url: str): return []
            def fetchChapter(self, url: str): raise NotImplementedError
            def getSelectors(self): return Selectors(start=None, end=None)

        adapters = [FastAdapter(), SlowAdapter(), FailingAdapter()]
        start = time.time()
        results = search_all("Lord of Mysteries", adapters)
        elapsed = time.time() - start
        # dedupe (site,url) -> should be 2 unique urls
        assert len(results) == 2
        urls = {r.url for r in results}
        assert "https://www.novelphoenix.com/novel/1" in urls
        assert "https://www.novelphoenix.com/novel/2" in urls
        # <5s per site parallel (overall <2s even with sleeps)
        assert elapsed < 5
        # failing adapter contributes []
        # no exception raised
        assert elapsed < 2

    @patch("adapters._http.time.sleep", return_value=None)
    def test_search_all_timeout_per_site(self, mock_sleep):
        class SlowTimeoutAdapter(ScraperPort):
            def search(self, title: str):
                _real_sleep(6)  # exceeds 5s per site
                return [SearchResult(site="novelphoenix.com", title="Late", url="https://www.novelphoenix.com/novel/late")]
            def listChapters(self, url: str): return []
            def fetchChapter(self, url: str): raise NotImplementedError
            def getSelectors(self): return Selectors(start=None, end=None)

        class FastAdapter(ScraperPort):
            def search(self, title: str):
                return [SearchResult(site="novelphoenix.com", title="Fast", url="https://www.novelphoenix.com/novel/fast")]
            def listChapters(self, url: str): return []
            def fetchChapter(self, url: str): raise NotImplementedError
            def getSelectors(self): return Selectors(start=None, end=None)

        adapters = [FastAdapter(), SlowTimeoutAdapter()]
        start = time.time()
        results = search_all("test", adapters)
        elapsed = time.time() - start
        # Should return fast result, timeout adapter contributes []
        assert len(results) == 1
        assert results[0].title == "Fast"
        # should timeout at ~5s
        assert 5 <= elapsed < 7

    def test_search_all_empty_adapters(self):
        assert search_all("title", []) == []

    def test_search_all_value_error_fault_isolate(self):
        class BadAdapter(ScraperPort):
            def search(self, title: str):
                raise ValueError("empty")
            def listChapters(self, url: str): return []
            def fetchChapter(self, url: str): raise NotImplementedError
            def getSelectors(self): return Selectors(start=None, end=None)
        results = search_all("", [BadAdapter()])
        assert results == []


# ------------------------------------------------------------------ issubclass and SearchResult frozen
def test_issubclass_and_frozen():
    assert issubclass(NovelPhoenixAdapter, ScraperPort)
    sr = SearchResult(site="novelphoenix.com", title="t", url="https://example.com")
    # frozen -> cannot mutate
    with pytest.raises(Exception):
        sr.title = "new"  # type: ignore
    assert sr.cover_url is None
    assert sr.author is None
    # with cover_url
    sr2 = SearchResult(site="novelphoenix.com", title="t", url="https://example.com", cover_url="https://example.com/c.jpg", author="Author")
    assert sr2.cover_url == "https://example.com/c.jpg"
    assert sr2.author == "Author"
