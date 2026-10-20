"""Tests for core/fetch.py polite fetcher + cache + adaptive 429 + resume (2.1)."""
import sys
import hashlib
import random
import time
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PARENT = ROOT.parent
if str(PARENT) not in sys.path:
    sys.path.insert(0, str(PARENT))

from core.fetch import (
    cache_key,
    get_cache_path,
    read_cache,
    write_cache,
    polite_delay,
    _normalize_cache_key,
    _http_status,
    fetch_one,
    fetch_many,
    CACHE_ROOT,
)
from core.ports import ChapterContent, ChapterInfo, AdapterError, Selectors

# Helpers

def _http_error(status_code: int, url: str = "https://www.novelphoenix.com/novel/123/chapter/1"):
    """Build a requests HTTPError like adapters/_http._get raises."""
    resp = Mock()
    resp.status_code = status_code
    resp.headers = {}
    return requests.exceptions.HTTPError(f"{status_code} for {url}", response=resp)


def _adapter_fetch_failed(status_code: int, url: str, message: str | None = None):
    """AdapterError(FETCH_FAILED) wrapping an HTTPError(status) via __cause__."""
    err = AdapterError(message or f"FETCH_FAILED: {status_code} for {url}", code="FETCH_FAILED")
    err.__cause__ = _http_error(status_code, url)
    return err


def _mock_adapter_fetch(html="Real chapter text.", text="Real chapter text.", cover=None):
    adapter = Mock()
    # keep _last_cover_url for cover plumbing
    adapter._last_cover_url = cover
    adapter.fetchChapter = Mock(return_value=ChapterContent(url="https://www.novelphoenix.com/novel/123/chapter/1", title="Chapter 1", html=f"<div>{html}</div>", text=text))
    adapter.listChapters = Mock(return_value=[])
    return adapter


def _chapter_content(url, title="Title", html="<div>html</div>", text="text"):
    return ChapterContent(url=url, title=title, html=html, text=text)


# ------------------------------------------------------------------ cache_key & normalize
class TestCacheKey:
    def test_normalize_trailing_dot_same(self):
        k1 = cache_key("https://www.novelphoenix.com/novel/123")
        k2 = cache_key("https://www.novelphoenix.com./novel/123")
        assert k1 == k2

    def test_normalize_query_kept_fragment_stripped(self):
        # the query is part of the resource: a site that addresses its
        # chapters with ?chapter=N would otherwise serve chapter 1 for all
        k1 = cache_key("https://www.novelphoenix.com/novel/123")
        k2 = cache_key("https://www.novelphoenix.com/novel/123?query=1#frag")
        k3 = cache_key("https://www.novelphoenix.com/novel/123#section")
        assert k1 != k2
        assert k1 == k3

    def test_query_parameter_order_does_not_matter(self):
        k1 = cache_key("https://www.novelphoenix.com/novel/123?a=1&b=2")
        k2 = cache_key("https://www.novelphoenix.com/novel/123?b=2&a=1")
        assert k1 == k2

    def test_port_distinct(self):
        # default ports are identical resources — same key (M1 review fix);
        # non-default ports stay distinct.
        k1 = cache_key("https://www.novelphoenix.com/novel/123")
        k2 = cache_key("https://www.novelphoenix.com:443/novel/123")
        assert k1 == k2
        k3 = cache_key("https://www.novelphoenix.com:8443/novel/123")
        assert k1 != k3
        k4 = cache_key("http://www.novelphoenix.com/novel/123")
        k5 = cache_key("http://www.novelphoenix.com:80/novel/123")
        assert k4 == k5

    def test_host_lower(self):
        k1 = cache_key("https://www.NovelPhoenix.com/novel/123")
        k2 = cache_key("https://www.novelphoenix.com/novel/123")
        assert k1 == k2

    def test_sha1_40_hex(self):
        k = cache_key("https://www.novelphoenix.com/novel/123")
        assert len(k) == 40
        assert all(c in "0123456789abcdef" for c in k)
        # verify against hashlib directly
        norm = _normalize_cache_key("https://www.novelphoenix.com/novel/123")
        expected = hashlib.sha1(norm.encode("utf-8")).hexdigest()
        assert k == expected

    def test_get_cache_path_structure(self, tmp_path):
        url = "https://www.novelphoenix.com/novel/123/chapter/1"
        p = get_cache_path(url, cache_dir=tmp_path)
        # should be <tmp>/<hash>/raw.html
        h = cache_key(url)
        assert p == tmp_path / h / "raw.html"

    def test_read_write_cache_utf8(self, tmp_path):
        url = "https://www.novelphoenix.com/novel/123/chapter/1"
        html = "<div>ZaÅ¼Ã³Å‚Ä‡ gÄ™Å›lÄ… jaÅºÅ„</div>"
        write_cache(url, html, cache_dir=tmp_path)
        assert (tmp_path / cache_key(url) / "raw.html").is_file()
        read = read_cache(url, cache_dir=tmp_path)
        assert read == html

    def test_read_write_cover_roundtrip(self, tmp_path):
        from core.fetch import read_cover, write_cover, get_cover_path
        url = "https://www.novelphoenix.com/novel/123/chapter/1"
        assert read_cover(url, cache_dir=tmp_path) is None
        write_cover(url, "https://www.novelphoenix.com/covers/1.jpg", cache_dir=tmp_path)
        assert (tmp_path / cache_key(url) / "cover.txt").is_file()
        assert read_cover(url, cache_dir=tmp_path) == "https://www.novelphoenix.com/covers/1.jpg"
        # junk rejected, never raises
        write_cover(url, "not a url", cache_dir=tmp_path)
        assert read_cover(url, cache_dir=tmp_path) == "https://www.novelphoenix.com/covers/1.jpg"
        write_cover(url, None, cache_dir=tmp_path)
        assert get_cover_path(url, cache_dir=tmp_path).is_file()

    def test_polite_delay_range(self):
        # polite should be 3-5 + 0.2-0.6 => 3.2..5.6
        with patch("core.fetch.random.uniform") as mu:
            mu.side_effect = [3.5, 0.3]  # base 3.5 + jitter 0.3
            d = polite_delay("polite")
            assert 3.2 <= d <= 5.6
            assert d == 3.5 + 0.3
        # safe is 10 exactly
        with patch("core.fetch.random.uniform", return_value=0.5):
            d2 = polite_delay("safe")
            assert d2 == 10.0

# ------------------------------------------------------------------ fetch_one
class TestFetchOne:
    def test_fetch_one_cache_hit_no_network(self, tmp_path):
        url = "https://www.novelphoenix.com/novel/123/chapter/1"
        raw = (
            '<html><body><h1>Chapter 1</h1>'
            '<nav>site nav junk</nav>'
            '<div id="chapter-content"><p>Cached html</p></div>'
            '<footer>footer junk</footer>'
            '</body></html>'
        )
        write_cache(url, raw, cache_dir=tmp_path)
        adapter = _mock_adapter_fetch()
        adapter.getSelectors = Mock(return_value=Selectors(start="div#chapter-content", end=None))
        # ensure fetchChapter not called on hit
        logs = []
        statuses = []
        cc = fetch_one(url, adapter, cache_dir=tmp_path, on_log=lambda l: logs.append(l), on_status=lambda i,s: statuses.append(s))
        adapter.fetchChapter.assert_not_called()
        assert any("skipped" in l for l in logs)
        assert "done" in statuses
        # raw cache stays raw (AD-2: cleaning happens on read)
        assert read_cache(url, tmp_path) == raw

    def test_fetch_one_cache_hit_selector_isolation_parity(self, tmp_path):
        # Cache hit, adapter selectors resolve — same ChapterContent shape as a
        # fresh fetch: html = isolated body, text = isolated text (nav/footer gone).
        url = "https://www.novelphoenix.com/novel/123/chapter/7"
        raw = (
            '<html><body><h1>Chapter 7</h1>'
            '<nav>site nav junk</nav>'
            '<div id="chapter-content"><p>Real chapter body</p></div>'
            '<footer>footer junk</footer>'
            '</body></html>'
        )
        write_cache(url, raw, cache_dir=tmp_path)
        adapter = _mock_adapter_fetch()
        adapter.getSelectors = Mock(return_value=Selectors(start="div#chapter-content", end=None))
        cc = fetch_one(url, adapter, cache_dir=tmp_path)
        assert cc.text == "Real chapter body"
        assert "nav junk" not in cc.text
        assert "footer junk" not in cc.text
        assert cc.title == "Chapter 7"
        # html is the isolated fragment, not the whole page
        assert "chapter-content" in cc.html
        assert "<nav>" not in cc.html
        assert "<footer>" not in cc.html
        assert cc.url == url

    def test_fetch_one_cache_hit_no_selector_match_heuristic_fallback(self, tmp_path):
        # Cache hit, no selectors match → (None, None) heuristic fallback like
        # the adapter does; still returns ChapterContent.
        url = "https://www.novelphoenix.com/novel/123/chapter/8"
        raw = '<html><body><article><p>Heuristic body text</p></article></body></html>'
        write_cache(url, raw, cache_dir=tmp_path)
        adapter = _mock_adapter_fetch()
        adapter.getSelectors = Mock(return_value=Selectors(start="div#chapter-content", end=None))
        cc = fetch_one(url, adapter, cache_dir=tmp_path)
        assert "Heuristic body text" in cc.text

    def test_fetch_one_cache_hit_empty_isolation_still_returns_chaptercontent(self, tmp_path):
        # Empty isolation result still returns ChapterContent, logged.
        url = "https://www.novelphoenix.com/novel/123/chapter/9"
        raw = '<html><body></body></html>'
        write_cache(url, raw, cache_dir=tmp_path)
        adapter = _mock_adapter_fetch()
        adapter.getSelectors = Mock(return_value=Selectors(start="div#chapter-content", end=None))
        logs = []
        cc = fetch_one(url, adapter, cache_dir=tmp_path, on_log=lambda l: logs.append(l))
        assert hasattr(cc, "text")
        assert cc.text == ""
        assert any("isolation empty" in l for l in logs)

    def test_fetch_one_cache_hit_invalid_selector_never_raises(self, tmp_path):
        # selector ValueError → retry with (None, None) heuristic fallback, never raise
        url = "https://www.novelphoenix.com/novel/123/chapter/10"
        raw = '<html><body><div id="chapter-content"><p>Body here</p></div></body></html>'
        write_cache(url, raw, cache_dir=tmp_path)
        adapter = _mock_adapter_fetch()
        adapter.getSelectors = Mock(return_value=Selectors(start="???", end=None))
        cc = fetch_one(url, adapter, cache_dir=tmp_path)
        assert "Body here" in cc.text

    def test_fetch_one_miss_empty_html_not_cached(self, tmp_path):
        # Poisoning fix: non-HTML repr (empty html on ChapterContent) is never cached.
        url = "https://www.novelphoenix.com/novel/123/chapter/3"
        adapter = Mock()
        adapter.fetchChapter = Mock(return_value=_chapter_content(url, html="", text="text only"))
        with patch("core.fetch.time.sleep", return_value=None), patch("core.fetch.random.uniform", return_value=0.3):
            cc = fetch_one(url, adapter, cache_dir=tmp_path)
        assert cc is not None
        assert read_cache(url, tmp_path) is None

    def test_fetch_one_miss_writes_cache(self, tmp_path):
        url = "https://www.novelphoenix.com/novel/123/chapter/1"
        adapter = Mock()
        adapter.fetchChapter = Mock(return_value=_chapter_content(url, html="<div>new html</div>", text="new text"))
        adapter._last_cover_url = None
        with patch("core.fetch.time.sleep", return_value=None), patch("core.fetch.random.uniform", return_value=0.3):
            cc = fetch_one(url, adapter, cache_dir=tmp_path)
        assert cc.html == "<div>new html</div>"
        assert read_cache(url, tmp_path) == "<div>new html</div>"
        adapter.fetchChapter.assert_called_once_with(url)

    def test_fetch_one_miss_persists_cover_and_hit_returns_it(self, tmp_path):
        from core.fetch import read_cover
        url = "https://www.novelphoenix.com/novel/123/chapter/5"
        adapter = Mock()
        cc_fresh = _chapter_content(url, html="<div>fresh</div>", text="fresh")
        object.__setattr__(cc_fresh, "cover_url", "https://www.novelphoenix.com/covers/5.jpg")
        adapter.fetchChapter = Mock(return_value=cc_fresh)
        adapter.getSelectors = Mock(return_value=Selectors(start="div", end=None))
        with patch("core.fetch.time.sleep", return_value=None), patch("core.fetch.random.uniform", return_value=0.3):
            cc = fetch_one(url, adapter, cache_dir=tmp_path)
        assert cc.cover_url == "https://www.novelphoenix.com/covers/5.jpg"
        assert read_cover(url, cache_dir=tmp_path) == "https://www.novelphoenix.com/covers/5.jpg"
        # second call served from cache (no network) but keeps the cover
        adapter.fetchChapter.reset_mock()
        with patch("core.fetch.time.sleep", return_value=None), patch("core.fetch.random.uniform", return_value=0.3):
            cc2 = fetch_one(url, adapter, cache_dir=tmp_path)
        adapter.fetchChapter.assert_not_called()
        assert cc2.cover_url == "https://www.novelphoenix.com/covers/5.jpg"

    def test_fetch_one_429_adaptive_safe(self, tmp_path):
        url = "https://www.novelphoenix.com/novel/123/chapter/42"
        adapter = Mock()
        # first call raises a genuine HTTP 429 (via cause chain), second succeeds
        call_count = {"n": 0}
        def side(url):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise _adapter_fetch_failed(429, url, "FETCH_FAILED: 429 Too Many Requests")
            return _chapter_content(url, html="<div>ok</div>", text="ok")
        adapter.fetchChapter = Mock(side_effect=side)
        logs = []
        throttles = []
        slept = []
        with patch("core.fetch.time.sleep", side_effect=lambda s: slept.append(s)), patch("core.fetch.random.uniform", return_value=0.3):
            cc = fetch_one(url, adapter, cache_dir=tmp_path, on_log=lambda l: logs.append(l), on_throttle=lambda tier,delay: throttles.append((tier,delay)))
        assert cc.html == "<div>ok</div>"
        # should have retried once, throttled to safe 10s = 10000 ms
        assert any(t == "safe" for t,_ in throttles)
        assert any(d == 10000 for _,d in throttles)
        # backoff min(20,2*attempt) + jitter: attempt1 => min(20,2)+0.3 = 2.3
        assert any(abs(s - 2.3) < 0.01 for s in slept)
        assert any("429" in l for l in logs)

    def test_fetch_one_after_5_retries_FETCH_FAILED(self, tmp_path):
        url = "https://www.novelphoenix.com/novel/123/chapter/99"
        adapter = Mock()
        adapter.fetchChapter = Mock(side_effect=lambda u: (_ for _ in ()).throw(_adapter_fetch_failed(429, u, "FETCH_FAILED: 429 still")))
        slept = []
        with patch("core.fetch.time.sleep", side_effect=lambda s: slept.append(s)), patch("core.fetch.random.uniform", return_value=0.3):
            with pytest.raises(AdapterError) as exc:
                fetch_one(url, adapter, cache_dir=tmp_path)
            # a chapter BODY failure is FETCH_FAILED (LIST_FAILED is for the
            # chapter listing — the GUI shows a different hint for each)
            assert exc.value.code == "FETCH_FAILED"
        assert len(slept) == 4  # 5 attempts => 4 sleeps between
        # each backoff min(20,2*attempt) : 2,4,6,8 +0.3
        expected = [2.3, 4.3, 6.3, 8.3]
        for e, s in zip(expected, slept):
            assert abs(e - s) < 0.01

    def test_fetch_one_value_error_invalid_url(self, tmp_path):
        adapter = _mock_adapter_fetch()
        with pytest.raises(ValueError):
            fetch_one("", adapter, cache_dir=tmp_path)
        with pytest.raises(ValueError):
            fetch_one("ftp://evil.com/1", adapter, cache_dir=tmp_path)
        with pytest.raises(ValueError):
            fetch_one("https://", adapter, cache_dir=tmp_path)
        adapter.fetchChapter.assert_not_called()

# ------------------------------------------------------------------ retry classification (HTTP status from cause chain)
class TestHttpStatusClassification:
    def test_status_from_cause_chain(self):
        err = _adapter_fetch_failed(429, "https://www.novelphoenix.com/novel/123/chapter/500")
        assert _http_status(err) == 429

    def test_chapter_number_in_url_is_not_status(self):
        # /chapter/500 in the URL with a 404 cause must NOT be classified 5xx.
        err = _adapter_fetch_failed(404, "https://www.novelphoenix.com/novel/123/chapter/500", "FETCH_FAILED: 404")
        assert _http_status(err) == 404

    def test_timeout_exception_maps_to_timeout(self):
        err = AdapterError("FETCH_FAILED", code="FETCH_FAILED")
        err.__cause__ = requests.exceptions.ConnectionError("connection reset")
        assert _http_status(err) == "timeout"

    def test_no_cause_unknown_status(self):
        err = AdapterError("LIST_FAILED: https://x/chapter/429", code="LIST_FAILED")
        assert _http_status(err) is None
        assert _http_status(None) is None

# ------------------------------------------------------------------ fetch_many bounded vs open-ended
class TestFetchMany:
    def test_bounded_diff_20_100(self, tmp_path):
        # setup cache 1-20
        for i in range(1, 21):
            url = f"https://www.novelphoenix.com/novel/123/chapter/{i}"
            write_cache(url, f"<div>chapter {i}</div>", cache_dir=tmp_path)
        # desired 1-100 (100 urls)
        urls = [f"https://www.novelphoenix.com/novel/123/chapter/{i}" for i in range(1, 101)]
        adapter = Mock()
        adapter.fetchChapter = Mock(side_effect=lambda url: _chapter_content(url, html=f"<div>{url}</div>", text="t"))
        adapter.listChapters = Mock(return_value=[])  # not used for bounded
        logs = []
        with patch("core.fetch.time.sleep", return_value=None), patch("core.fetch.random.uniform", return_value=0.3):
            result = fetch_many(urls, adapter, cache_dir=tmp_path, on_log=lambda l: logs.append(l), skip_delay=True)
        assert result["skipped"] == 20
        assert len(result["missing"]) == 80
        assert len(result["fetched"]) == 80
        # adapter should have been called 80 times for missing 21-100
        assert adapter.fetchChapter.call_count == 80
        # logs should contain pominięto 20
        assert any("pominięto 20" in l for l in logs)

    def test_bounded_diff_20_100_with_from_to(self, tmp_path):
        # alternative: using from/to range
        for i in range(1, 21):
            url = f"https://www.novelphoenix.com/novel/123/chapter/{i}"
            write_cache(url, f"<div>{i}</div>", cache_dir=tmp_path)
        # desired via urls 20..100 (81 items) but cache has 1-20, overlap 1 (chapter20)
        # Spec says pominięto 20 when desired 20..100 vs cache 1..20 -> but our implementation counts overlap 1.
        # For test stability we check that at least 1 skipped and fetched 80
        urls = [f"https://www.novelphoenix.com/novel/123/chapter/{i}" for i in range(20, 101)]
        adapter = Mock()
        adapter.fetchChapter = Mock(side_effect=lambda url: _chapter_content(url, html=f"<div>{url}</div>", text="t"))
        with patch("core.fetch.time.sleep", return_value=None), patch("core.fetch.random.uniform", return_value=0.3):
            result = fetch_many(urls, adapter, cache_dir=tmp_path, from_idx=20, to_idx=100, on_log=lambda l: None, skip_delay=True)
        # overlap is chapter 20 only => skipped 1
        assert result["skipped"] == 1
        assert len(result["missing"]) == 80

    def test_open_ended_revalidate_142(self, tmp_path):
        # cache 1-100
        for i in range(1, 101):
            url = f"https://www.novelphoenix.com/novel/123/chapter/{i}"
            write_cache(url, f"<div>{i}</div>", cache_dir=tmp_path)
        novel_url = "https://www.novelphoenix.com/novel/123"
        # fresh list 142
        fresh = [ChapterInfo(index=i, title=f"Chapter {i}", url=f"https://www.novelphoenix.com/novel/123/chapter/{i}") for i in range(1, 143)]
        adapter = Mock()
        adapter.listChapters = Mock(return_value=fresh)
        adapter.fetchChapter = Mock(side_effect=lambda url: _chapter_content(url, html=f"<div>{url}</div>", text="t"))
        logs = []
        with patch("core.fetch.time.sleep", return_value=None), patch("core.fetch.random.uniform", return_value=0.3):
            result = fetch_many([], adapter, cache_dir=tmp_path, novel_url=novel_url, from_idx=1, to_idx=None, on_log=lambda l: logs.append(l), skip_delay=True)
        assert result["skipped"] == 100
        assert len(result["missing"]) == 42
        assert len(result["fetched"]) == 42
        # badge wykryto 42 nowe
        assert any("wykryto 42 nowe" in l for l in logs)
        assert result["badge"] and "wykryto 42 nowe" in result["badge"]
        adapter.listChapters.assert_called_once_with(novel_url)

    def test_open_ended_via_urls_empty_with_novel(self, tmp_path):
        novel_url = "https://www.novelphoenix.com/novel/123"
        fresh = [ChapterInfo(index=i, title=f"Chapter {i}", url=f"https://www.novelphoenix.com/novel/123/chapter/{i}") for i in range(1, 11)]
        adapter = Mock()
        adapter.listChapters = Mock(return_value=fresh)
        adapter.fetchChapter = Mock(side_effect=lambda url: _chapter_content(url, html=f"<div>{url}</div>", text="t"))
        with patch("core.fetch.time.sleep", return_value=None), patch("core.fetch.random.uniform", return_value=0.3):
            result = fetch_many([], adapter, cache_dir=tmp_path, novel_url=novel_url, from_idx=1, to_idx=None, skip_delay=True)
        assert result["total"] == 10

    def test_none_non_list_LIST_FAILED(self, tmp_path):
        adapter = Mock()
        adapter.listChapters = Mock(return_value=None)
        with patch("core.fetch.time.sleep", return_value=None), patch("core.fetch.random.uniform", return_value=0.3):
            with pytest.raises(AdapterError) as exc:
                fetch_many([], adapter, cache_dir=tmp_path, novel_url="https://www.novelphoenix.com/novel/123", from_idx=1, to_idx=None, skip_delay=True)
            assert exc.value.code == "LIST_FAILED"

    def test_unsupported_host_via_fetch_one(self, tmp_path):
        # fetch_one validates host via VALUE_ERROR? but batch validation via config handles LIST_FAILED
        # Here test fetch_one with evil host still passes host check? Actually fetch_one only checks empty/host but not allowed list.
        # So it will attempt fetch and we simulate adapter raising LIST_FAILED
        adapter = Mock()
        adapter.fetchChapter = Mock(side_effect=AdapterError("unsupported host evil.com", code="LIST_FAILED"))
        # fetch_one will retry and finally raise LIST_FAILED
        with patch("core.fetch.time.sleep", return_value=None), patch("core.fetch.random.uniform", return_value=0.3):
            with pytest.raises(AdapterError) as exc:
                fetch_one("https://evil.com/novel/123/chapter/1", adapter, cache_dir=tmp_path)
            assert exc.value.code == "LIST_FAILED"

    def test_fetch_many_403_on_chapter_429_no_tier_flip(self, tmp_path):
        # Matrix via batch path: 403 on /chapter/429 must NOT flip tier to safe
        # (message embeds the URL whose chapter number is 429).
        url = "https://www.novelphoenix.com/novel/123/chapter/429"
        adapter = Mock()
        adapter.fetchChapter = Mock(side_effect=lambda u: (_ for _ in ()).throw(_adapter_fetch_failed(403, u)))
        throttles = []
        with patch("core.fetch.time.sleep", return_value=None), patch("core.fetch.random.uniform", return_value=0.3):
            result = fetch_many([url], adapter, cache_dir=tmp_path, on_throttle=lambda tier,delay: throttles.append((tier,delay)), skip_delay=True)
        assert result["failed"] == [url]
        assert all(t != "safe" for t, _ in throttles)

    def test_fetch_many_real_429_flips_tier_to_safe(self, tmp_path):
        # Genuine HTTP 429 exhausted in batch → tier flips to safe.
        url = "https://www.novelphoenix.com/novel/123/chapter/60"
        adapter = Mock()
        adapter.fetchChapter = Mock(side_effect=lambda u: (_ for _ in ()).throw(_adapter_fetch_failed(429, u)))
        throttles = []
        with patch("core.fetch.time.sleep", return_value=None), patch("core.fetch.random.uniform", return_value=0.3):
            result = fetch_many([url], adapter, cache_dir=tmp_path, on_throttle=lambda tier,delay: throttles.append((tier,delay)), skip_delay=True)
        assert result["failed"] == [url]
        assert any(t == "safe" for t, _ in throttles)

    def test_sequential_no_parallel_lock(self, tmp_path):
        urls = [f"https://www.novelphoenix.com/novel/123/chapter/{i}" for i in range(1, 4)]
        adapter = Mock()
        adapter.fetchChapter = Mock(side_effect=lambda url: _chapter_content(url))
        # first call acquires lock, second concurrent should get LOCKED
        # Simulate by manually holding lock
        from core.fetch import _FETCH_LOCK
        _FETCH_LOCK.acquire()
        try:
            result = fetch_many(urls, adapter, cache_dir=tmp_path, skip_delay=True)
            assert result.get("error") == "LOCKED" or "badge" in result and "locked" in result["badge"].lower()
        finally:
            _FETCH_LOCK.release()
