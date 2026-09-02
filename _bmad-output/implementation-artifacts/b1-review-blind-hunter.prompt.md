Conduct a review of CONTENT.
Look for what's missing, not only what's wrong.
Find at least ten issues to fix or improve.
Output a Markdown list of findings only - no severity, priority, or ranking.
If the content is empty, stop and say so.
If you have zero findings, re-check and keep thinking; do not stop with an empty list.

CONTENT:
diff --git a/Speak-EPUB-1.0.0/core/config.py b/Speak-EPUB-1.0.0/core/config.py
index 63ff25f..cafcc58 100644
--- a/Speak-EPUB-1.0.0/core/config.py
+++ b/Speak-EPUB-1.0.0/core/config.py
@@ -1240,9 +1240,11 @@ def handle_rpc(request: Any, emit_fn=None) -> Dict[str, Any]:
             except Exception:
                 raw_html = None
             if raw_html is None:
-                # fallback: try adapters._http._get raw fetch without cache (no write)
+                # fallback: Core-owned polite raw fetch without cache (no write);
+                # core.http mirrors adapters/_http.py politeness values without
+                # importing an adapter module (core-no-adapters contract)
                 try:
-                    from adapters._http import _get as _http_get
+                    from core.http import _get as _http_get
 
                     resp = _http_get(url_param, timeout=12, retries=2)
                     raw_html = resp.text or ""
diff --git a/Speak-EPUB-1.0.0/core/fetch.py b/Speak-EPUB-1.0.0/core/fetch.py
index 431fdee..76eb01a 100644
--- a/Speak-EPUB-1.0.0/core/fetch.py
+++ b/Speak-EPUB-1.0.0/core/fetch.py
@@ -107,6 +107,63 @@ def _backoff_delay(attempt: int) -> float:
     """Exponential backoff cap 20s + jitter 0.2–0.6, attempt 1-based."""
     return min(20, 2 * attempt) + random.uniform(0.2, 0.6)
 
+
+def _http_status(exc: BaseException | None) -> int | str | None:
+    """Derive the HTTP status behind *exc* from the exception chain.
+
+    The adapter wraps the transport error: AdapterError(FETCH_FAILED) → cause
+    HTTPError(response=resp) → resp.status_code, so the status lives on the
+    ``__cause__`` chain, not on the raised exception itself. This helper climbs
+    that chain looking for ``.response.status_code`` and maps
+    Timeout/ConnectionError to the literal ``"timeout"``.
+
+    As a last resort it substring-matches the ``code`` attribute only — never
+    ``str(exc)``, whose message embeds the target URL and its chapter numbers
+    (``/chapter/500``, ``/chapter/429``) that must not be misread as status
+    codes.
+
+    Returns an int status, ``"timeout"``, ``"5xx"`` or None when unknown.
+    """
+    if exc is None:
+        return None
+    seen: set[int] = set()
+    cur: BaseException | None = exc
+    while cur is not None and id(cur) not in seen:
+        seen.add(id(cur))
+        resp = getattr(cur, "response", None)
+        status = getattr(resp, "status_code", None)
+        if isinstance(status, int) and not isinstance(status, bool):
+            return status
+        cname = type(cur).__name__
+        if "Timeout" in cname or "ConnectionError" in cname:
+            return "timeout"
+        code = getattr(cur, "code", None)
+        if isinstance(code, str) and code:
+            low = code.lower()
+            if "timeout" in low:
+                return "timeout"
+            if "429" in code:
+                return 429
+            m = re.search(r"\b5\d\d\b", code)
+            if m:
+                return int(m.group(0))
+            if "5xx" in low:
+                return "5xx"
+        cur = getattr(cur, "__cause__", None)
+    return None
+
+
+def _retry_class(exc: BaseException | None) -> tuple[bool, bool, bool]:
+    """Classify exception as (is_429, is_5xx, is_timeout) from _http_status."""
+    status = _http_status(exc)
+    if status == "timeout":
+        return (False, False, True)
+    if status == "5xx":
+        return (False, True, False)
+    if isinstance(status, int) and not isinstance(status, bool):
+        return (status == 429, 500 <= status < 600, False)
+    return (False, False, False)
+
 # ---------------------------------------------------------------------------
 # fetch_one — sequential, cache-aware, adaptive 429
 # ---------------------------------------------------------------------------
@@ -163,26 +220,44 @@ def fetch_one(
                 on_status(status_idx if status_idx is not None else 0, "done")
             except Exception:
                 pass
-        # Build ChapterContent from cached html (raw not filtered, but parse title/text)
+        # Clean through the SAME resolve_selectors + clean_html pipeline a fresh
+        # fetch uses, so cache-hit and fresh-fetch return the same ChapterContent
+        # shape (html = isolated body HTML, text = isolated text). Raw cache is
+        # never rewritten — cleaning happens on read (AD-2).
+        cleaned_html = cached
+        cleaned_text = ""
+        try:
+            from core.clean import resolve_selectors, clean_html
+
+            sel = resolve_selectors(adapter)
+            cleaned_html, cleaned_text = clean_html(cached, sel.start, sel.end)
+        except ValueError:
+            # invalid override/default selector → heuristic fallback, never raise
+            try:
+                from core.clean import clean_html as _clean_fallback
+
+                cleaned_html, cleaned_text = _clean_fallback(cached, None, None)
+            except Exception:
+                cleaned_html, cleaned_text = cached, ""
+        except Exception:
+            cleaned_html, cleaned_text = cached, ""
+        # title fallback (same as before)
         try:
             from bs4 import BeautifulSoup
 
             soup = BeautifulSoup(cached, "lxml")
-            # title fallback
             ttag = soup.find(["h1", "h2", "h3"])
             title = ttag.get_text(strip=True) if ttag else url
-            # text naive
-            for tag in soup(["script", "style", "nav", "aside"]):
-                tag.decompose()
-            body = soup
-            text = body.get_text(separator=" ", strip=True)
-            text = re.sub(r"\s+", " ", text).strip()
-            from core.ports import ChapterContent
-
-            return ChapterContent(url=url, title=title or url, html=cached, text=text or cached)
         except Exception:
-            # fallback: return raw string if ChapterContent import fails
-            return cached
+            title = url
+        if not cleaned_text and on_log:
+            try:
+                on_log(f"cache-hit isolation empty {url}")
+            except Exception:
+                pass
+        from core.ports import ChapterContent
+
+        return ChapterContent(url=url, title=title or url, html=cleaned_html or cached, text=cleaned_text or "")
 
     tier = "polite"
     # initial throttle emit polite
@@ -209,14 +284,12 @@ def fetch_one(
             cc = adapter.fetchChapter(url)
             if cc is None or not hasattr(cc, "html"):
                 raise ValueError("adapter returned non-list")
-            # write cache raw.html (AD-2 raw never filtered)
+            # write cache raw.html (AD-2 raw never filtered); never cache a
+            # non-HTML repr — an empty html must not poison the cache
             try:
                 html_to_cache = getattr(cc, "html", "") or ""
                 if html_to_cache:
                     write_cache(url, html_to_cache, cache_dir)
-                else:
-                    # fallback to text if html missing
-                    write_cache(url, str(cc), cache_dir)
             except Exception:
                 pass
             if on_status:
@@ -234,10 +307,11 @@ def fetch_one(
             last_exc = e
             msg = str(e)
             code = getattr(e, "code", "")
-            # detect 429 / 5xx / timeout — only these are retryable; 404/403 LIST_FAILED is NOT retryable
-            is_429 = "429" in msg or "429" in code or "Too Many" in msg
-            is_5xx = bool(re.search(r"\b5\d\d\b", msg)) or "5xx" in msg.lower()
-            is_timeout = "timeout" in msg.lower() or "timed out" in msg.lower()
+            # detect 429 / 5xx / timeout from the exception chain's HTTP status —
+            # only these are retryable; 404/403 LIST_FAILED is NOT retryable.
+            # Never substring the message: it embeds URLs whose chapter numbers
+            # (/chapter/500, /chapter/429) must not flip retry/throttle tiers.
+            is_429, is_5xx, is_timeout = _retry_class(e)
             retryable = is_429 or is_5xx or is_timeout
             if not retryable:
                 if on_status:
@@ -637,8 +711,10 @@ def fetch_many(
                     except Exception:
                         pass
                 failed.append(url)
-                # adaptive tier already handled in fetch_one; update tier if 429
-                if "429" in str(e):
+                # adaptive tier already handled in fetch_one; update tier if genuine HTTP 429
+                # (status derived from the __cause__ chain — never from the message,
+                # which embeds chapter-number URLs like /chapter/429)
+                if _http_status(e) == 429:
                     tier = "safe"
                     if on_throttle:
                         try:
diff --git a/Speak-EPUB-1.0.0/core/http.py b/Speak-EPUB-1.0.0/core/http.py
new file mode 100644
index 0000000..fa78476
--- /dev/null
+++ b/Speak-EPUB-1.0.0/core/http.py
@@ -0,0 +1,83 @@
+"""core/http.py — Core-owned polite HTTP helper (AD-1 firewall).
+
+Mirrors adapters/_http.py politeness values exactly — UA SpeakEPUB/1.0,
+timeout 12s, retries 2, jitter 0.2-0.6s, backoff min(20, 2*attempt) — so
+behavior is indistinguishable from the adapter-local helper. Exists so
+core.config's preview fallback no longer imports an adapter module
+(core-no-adapters contract in .importlinter).
+
+Retry policy: on Timeout/ConnectionError and on HTTP 429/5xx always
+retry; on other 4xx also retry for robustness. Caller decides final
+mapping to [] or AdapterError.
+"""
+from __future__ import annotations
+
+import random
+import time
+
+import requests
+
+
+UA = "SpeakEPUB/1.0"
+_HEADERS = {"User-Agent": UA}
+
+
+def _get(url: str, timeout: float = 12, retries: int = 2) -> requests.Response:
+    """GET with polite UA, retry, jitter and capped backoff.
+
+    Retries `retries` times (total attempts = retries+1). Between attempts
+    sleeps `min(20, 2*attempt) + uniform(0.2,0.6)` to respect politeness.
+    Retries on network Timeout/ConnectionError and on HTTP 429 / 5xx;
+    also retries other 4xx for robustness (final caller maps to []).
+    Raises the last exception after exhausting retries.
+    """
+    if not isinstance(url, str) or not url.strip():
+        raise ValueError("invalid url")
+    if not isinstance(retries, int) or retries < 0:
+        retries = 2
+    if not isinstance(timeout, (int, float)) or timeout <= 0:
+        timeout = 12
+    last_exc: Exception | None = None
+    for attempt in range(retries + 1):
+        try:
+            resp = requests.get(url, headers=_HEADERS, timeout=timeout)
+            # Success
+            if resp.status_code < 400:
+                return resp
+            # Error status -> decide retry
+            # Treat 429 and 5xx as retryable
+            retryable = resp.status_code == 429 or 500 <= resp.status_code < 600
+            # For robustness, also retry other 4xx up to retries
+            if not retryable and 400 <= resp.status_code < 500:
+                retryable = True
+            if retryable and attempt < retries:
+                wait = min(20, 2 * (attempt + 1)) + random.uniform(0.2, 0.6)
+                time.sleep(wait)
+                continue
+            # After retries or non-retryable, raise to caller
+            # Attach response for caller to inspect status
+            http_err = requests.exceptions.HTTPError(
+                f"{resp.status_code} for {url}", response=resp
+            )
+            raise http_err
+        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
+            last_exc = e
+            if attempt < retries:
+                wait = min(20, 2 * (attempt + 1)) + random.uniform(0.2, 0.6)
+                time.sleep(wait)
+                continue
+            raise
+        except requests.exceptions.HTTPError:
+            # already handled retry above; re-raise if not retried
+            raise
+        except Exception as e:
+            last_exc = e
+            if attempt < retries:
+                wait = min(20, 2 * (attempt + 1)) + random.uniform(0.2, 0.6)
+                time.sleep(wait)
+                continue
+            raise
+    # Fallback (should not reach)
+    if last_exc is not None:
+        raise last_exc
+    raise RuntimeError(f"request failed after {retries} retries: {url}")
diff --git a/Speak-EPUB-1.0.0/tests/test_fetch.py b/Speak-EPUB-1.0.0/tests/test_fetch.py
index b388828..d015104 100644
--- a/Speak-EPUB-1.0.0/tests/test_fetch.py
+++ b/Speak-EPUB-1.0.0/tests/test_fetch.py
@@ -7,6 +7,7 @@ from pathlib import Path
 from unittest.mock import Mock, MagicMock, patch
 
 import pytest
+import requests
 
 ROOT = Path(__file__).resolve().parents[1]
 if str(ROOT) not in sys.path:
@@ -22,14 +23,30 @@ from core.fetch import (
     write_cache,
     polite_delay,
     _normalize_cache_key,
+    _http_status,
     fetch_one,
     fetch_many,
     CACHE_ROOT,
 )
-from core.ports import ChapterContent, ChapterInfo, AdapterError
+from core.ports import ChapterContent, ChapterInfo, AdapterError, Selectors
 
 # Helpers
 
+def _http_error(status_code: int, url: str = "https://www.novelphoenix.com/novel/123/chapter/1"):
+    """Build a requests HTTPError like adapters/_http._get raises."""
+    resp = Mock()
+    resp.status_code = status_code
+    resp.headers = {}
+    return requests.exceptions.HTTPError(f"{status_code} for {url}", response=resp)
+
+
+def _adapter_fetch_failed(status_code: int, url: str, message: str | None = None):
+    """AdapterError(FETCH_FAILED) wrapping an HTTPError(status) via __cause__."""
+    err = AdapterError(message or f"FETCH_FAILED: {status_code} for {url}", code="FETCH_FAILED")
+    err.__cause__ = _http_error(status_code, url)
+    return err
+
+
 def _mock_adapter_fetch(html="Real chapter text.", text="Real chapter text.", cover=None):
     adapter = Mock()
     # keep _last_cover_url for cover plumbing
@@ -106,17 +123,94 @@ class TestCacheKey:
 class TestFetchOne:
     def test_fetch_one_cache_hit_no_network(self, tmp_path):
         url = "https://www.novelphoenix.com/novel/123/chapter/1"
-        html = "<div>Cached html</div>"
-        write_cache(url, html, cache_dir=tmp_path)
+        raw = (
+            '<html><body><h1>Chapter 1</h1>'
+            '<nav>site nav junk</nav>'
+            '<div id="chapter-content"><p>Cached html</p></div>'
+            '<footer>footer junk</footer>'
+            '</body></html>'
+        )
+        write_cache(url, raw, cache_dir=tmp_path)
         adapter = _mock_adapter_fetch()
+        adapter.getSelectors = Mock(return_value=Selectors(start="div#chapter-content", end=None))
         # ensure fetchChapter not called on hit
         logs = []
         statuses = []
         cc = fetch_one(url, adapter, cache_dir=tmp_path, on_log=lambda l: logs.append(l), on_status=lambda i,s: statuses.append(s))
         adapter.fetchChapter.assert_not_called()
-        assert cc.html == html
         assert any("skipped" in l for l in logs)
         assert "done" in statuses
+        # raw cache stays raw (AD-2: cleaning happens on read)
+        assert read_cache(url, tmp_path) == raw
+
+    def test_fetch_one_cache_hit_selector_isolation_parity(self, tmp_path):
+        # Cache hit, adapter selectors resolve — same ChapterContent shape as a
+        # fresh fetch: html = isolated body, text = isolated text (nav/footer gone).
+        url = "https://www.novelphoenix.com/novel/123/chapter/7"
+        raw = (
+            '<html><body><h1>Chapter 7</h1>'
+            '<nav>site nav junk</nav>'
+            '<div id="chapter-content"><p>Real chapter body</p></div>'
+            '<footer>footer junk</footer>'
+            '</body></html>'
+        )
+        write_cache(url, raw, cache_dir=tmp_path)
+        adapter = _mock_adapter_fetch()
+        adapter.getSelectors = Mock(return_value=Selectors(start="div#chapter-content", end=None))
+        cc = fetch_one(url, adapter, cache_dir=tmp_path)
+        assert cc.text == "Real chapter body"
+        assert "nav junk" not in cc.text
+        assert "footer junk" not in cc.text
+        assert cc.title == "Chapter 7"
+        # html is the isolated fragment, not the whole page
+        assert "chapter-content" in cc.html
+        assert "<nav>" not in cc.html
+        assert "<footer>" not in cc.html
+        assert cc.url == url
+
+    def test_fetch_one_cache_hit_no_selector_match_heuristic_fallback(self, tmp_path):
+        # Cache hit, no selectors match → (None, None) heuristic fallback like
+        # the adapter does; still returns ChapterContent.
+        url = "https://www.novelphoenix.com/novel/123/chapter/8"
+        raw = '<html><body><article><p>Heuristic body text</p></article></body></html>'
+        write_cache(url, raw, cache_dir=tmp_path)
+        adapter = _mock_adapter_fetch()
+        adapter.getSelectors = Mock(return_value=Selectors(start="div#chapter-content", end=None))
+        cc = fetch_one(url, adapter, cache_dir=tmp_path)
+        assert "Heuristic body text" in cc.text
+
+    def test_fetch_one_cache_hit_empty_isolation_still_returns_chaptercontent(self, tmp_path):
+        # Empty isolation result still returns ChapterContent, logged.
+        url = "https://www.novelphoenix.com/novel/123/chapter/9"
+        raw = '<html><body></body></html>'
+        write_cache(url, raw, cache_dir=tmp_path)
+        adapter = _mock_adapter_fetch()
+        adapter.getSelectors = Mock(return_value=Selectors(start="div#chapter-content", end=None))
+        logs = []
+        cc = fetch_one(url, adapter, cache_dir=tmp_path, on_log=lambda l: logs.append(l))
+        assert hasattr(cc, "text")
+        assert cc.text == ""
+        assert any("isolation empty" in l for l in logs)
+
+    def test_fetch_one_cache_hit_invalid_selector_never_raises(self, tmp_path):
+        # selector ValueError → retry with (None, None) heuristic fallback, never raise
+        url = "https://www.novelphoenix.com/novel/123/chapter/10"
+        raw = '<html><body><div id="chapter-content"><p>Body here</p></div></body></html>'
+        write_cache(url, raw, cache_dir=tmp_path)
+        adapter = _mock_adapter_fetch()
+        adapter.getSelectors = Mock(return_value=Selectors(start="???", end=None))
+        cc = fetch_one(url, adapter, cache_dir=tmp_path)
+        assert "Body here" in cc.text
+
+    def test_fetch_one_miss_empty_html_not_cached(self, tmp_path):
+        # Poisoning fix: non-HTML repr (empty html on ChapterContent) is never cached.
+        url = "https://www.novelphoenix.com/novel/123/chapter/3"
+        adapter = Mock()
+        adapter.fetchChapter = Mock(return_value=_chapter_content(url, html="", text="text only"))
+        with patch("core.fetch.time.sleep", return_value=None), patch("core.fetch.random.uniform", return_value=0.3):
+            cc = fetch_one(url, adapter, cache_dir=tmp_path)
+        assert cc is not None
+        assert read_cache(url, tmp_path) is None
 
     def test_fetch_one_miss_writes_cache(self, tmp_path):
         url = "https://www.novelphoenix.com/novel/123/chapter/1"
@@ -132,12 +226,12 @@ class TestFetchOne:
     def test_fetch_one_429_adaptive_safe(self, tmp_path):
         url = "https://www.novelphoenix.com/novel/123/chapter/42"
         adapter = Mock()
-        # first call raises 429, second succeeds
+        # first call raises a genuine HTTP 429 (via cause chain), second succeeds
         call_count = {"n": 0}
         def side(url):
             call_count["n"] += 1
             if call_count["n"] == 1:
-                raise AdapterError("429 Too Many Requests", code="FETCH_FAILED")
+                raise _adapter_fetch_failed(429, url, "FETCH_FAILED: 429 Too Many Requests")
             return _chapter_content(url, html="<div>ok</div>", text="ok")
         adapter.fetchChapter = Mock(side_effect=side)
         logs = []
@@ -156,7 +250,7 @@ class TestFetchOne:
     def test_fetch_one_after_5_retries_LIST_FAILED(self, tmp_path):
         url = "https://www.novelphoenix.com/novel/123/chapter/99"
         adapter = Mock()
-        adapter.fetchChapter = Mock(side_effect=AdapterError("429 still", code="FETCH_FAILED"))
+        adapter.fetchChapter = Mock(side_effect=lambda u: (_ for _ in ()).throw(_adapter_fetch_failed(429, u, "FETCH_FAILED: 429 still")))
         slept = []
         with patch("core.fetch.time.sleep", side_effect=lambda s: slept.append(s)), patch("core.fetch.random.uniform", return_value=0.3):
             with pytest.raises(AdapterError) as exc:
@@ -178,6 +272,27 @@ class TestFetchOne:
             fetch_one("https://", adapter, cache_dir=tmp_path)
         adapter.fetchChapter.assert_not_called()
 
+# ------------------------------------------------------------------ retry classification (HTTP status from cause chain)
+class TestHttpStatusClassification:
+    def test_status_from_cause_chain(self):
+        err = _adapter_fetch_failed(429, "https://www.novelphoenix.com/novel/123/chapter/500")
+        assert _http_status(err) == 429
+
+    def test_chapter_number_in_url_is_not_status(self):
+        # /chapter/500 in the URL with a 404 cause must NOT be classified 5xx.
+        err = _adapter_fetch_failed(404, "https://www.novelphoenix.com/novel/123/chapter/500", "FETCH_FAILED: 404")
+        assert _http_status(err) == 404
+
+    def test_timeout_exception_maps_to_timeout(self):
+        err = AdapterError("FETCH_FAILED", code="FETCH_FAILED")
+        err.__cause__ = requests.exceptions.ConnectionError("connection reset")
+        assert _http_status(err) == "timeout"
+
+    def test_no_cause_unknown_status(self):
+        err = AdapterError("LIST_FAILED: https://x/chapter/429", code="LIST_FAILED")
+        assert _http_status(err) is None
+        assert _http_status(None) is None
+
 # ------------------------------------------------------------------ fetch_many bounded vs open-ended
 class TestFetchMany:
     def test_bounded_diff_20_100(self, tmp_path):
@@ -270,6 +385,29 @@ class TestFetchMany:
                 fetch_one("https://evil.com/novel/123/chapter/1", adapter, cache_dir=tmp_path)
             assert exc.value.code == "LIST_FAILED"
 
+    def test_fetch_many_403_on_chapter_429_no_tier_flip(self, tmp_path):
+        # Matrix via batch path: 403 on /chapter/429 must NOT flip tier to safe
+        # (message embeds the URL whose chapter number is 429).
+        url = "https://www.novelphoenix.com/novel/123/chapter/429"
+        adapter = Mock()
+        adapter.fetchChapter = Mock(side_effect=lambda u: (_ for _ in ()).throw(_adapter_fetch_failed(403, u)))
+        throttles = []
+        with patch("core.fetch.time.sleep", return_value=None), patch("core.fetch.random.uniform", return_value=0.3):
+            result = fetch_many([url], adapter, cache_dir=tmp_path, on_throttle=lambda tier,delay: throttles.append((tier,delay)), skip_delay=True)
+        assert result["failed"] == [url]
+        assert all(t != "safe" for t, _ in throttles)
+
+    def test_fetch_many_real_429_flips_tier_to_safe(self, tmp_path):
+        # Genuine HTTP 429 exhausted in batch → tier flips to safe.
+        url = "https://www.novelphoenix.com/novel/123/chapter/60"
+        adapter = Mock()
+        adapter.fetchChapter = Mock(side_effect=lambda u: (_ for _ in ()).throw(_adapter_fetch_failed(429, u)))
+        throttles = []
+        with patch("core.fetch.time.sleep", return_value=None), patch("core.fetch.random.uniform", return_value=0.3):
+            result = fetch_many([url], adapter, cache_dir=tmp_path, on_throttle=lambda tier,delay: throttles.append((tier,delay)), skip_delay=True)
+        assert result["failed"] == [url]
+        assert any(t == "safe" for t, _ in throttles)
+
     def test_sequential_no_parallel_lock(self, tmp_path):
         urls = [f"https://www.novelphoenix.com/novel/123/chapter/{i}" for i in range(1, 4)]
         adapter = Mock()
diff --git a/Speak-EPUB-1.0.0/tests/test_handle_rpc_preview.py b/Speak-EPUB-1.0.0/tests/test_handle_rpc_preview.py
index ac7747e..a533242 100644
--- a/Speak-EPUB-1.0.0/tests/test_handle_rpc_preview.py
+++ b/Speak-EPUB-1.0.0/tests/test_handle_rpc_preview.py
@@ -91,13 +91,34 @@ def test_previewChapter_end_selector():
 
 
 def test_previewChapter_no_cache_fallback_missing():
-    # when both cache and _get fail, should return LIST_FAILED
+    # when both cache and core.http._get fail, should return LIST_FAILED
     with patch("core.fetch.read_cache", return_value=None):
-        with patch("adapters._http._get", side_effect=Exception("network fail")):
+        with patch("core.http._get", side_effect=Exception("network fail")):
             r = handle_rpc({"id": "1", "method": "previewChapter", "params": {"url": _valid_url(), "start": "div#chapter-content"}})
             assert r["error"]["code"] == "LIST_FAILED"
 
 
+def test_previewChapter_no_cache_uses_core_http_fallback(tmp_path, monkeypatch):
+    # Matrix: config fallback fetch — no cache, core/http._get used, response
+    # handling identical to before (resp.text), still selector-isolated.
+    import core.clean as clean
+    monkeypatch.setattr(clean, "_OVERRIDES_DIR", tmp_path / "overrides")
+    raw = '<html><body><div id="chapter-content"><p>Fresh body</p><nav>nav</nav></div></body></html>'
+    mock_resp = Mock()
+    mock_resp.text = raw
+    with patch("core.fetch.read_cache", return_value=None):
+        with patch("core.http._get", return_value=mock_resp) as mock_get:
+            r = handle_rpc({"id": "1", "method": "previewChapter", "params": {"url": _valid_url(), "start": "div#chapter-content"}})
+            assert "result" in r
+            assert "Fresh body" in r["result"]["text"]
+            assert "nav" not in r["result"]["text"]
+            mock_get.assert_called_once()
+            args, kwargs = mock_get.call_args
+            assert args[0] == _valid_url()
+            assert kwargs.get("timeout") == 12
+            assert kwargs.get("retries") == 2
+
+
 def test_fetchChapter_uses_override(tmp_path, monkeypatch):
     import core.clean as clean
     monkeypatch.setattr(clean, "_OVERRIDES_DIR", tmp_path / "overrides")
diff --git a/package-lock.json b/package-lock.json
index fddcf86..d9939b4 100644
--- a/package-lock.json
+++ b/package-lock.json
@@ -11,6 +11,7 @@
         "@tauri-apps/api": "^2.11.0",
         "@tauri-apps/plugin-shell": "^2.3.5",
         "@tauri-apps/plugin-store": "^2.4.4",
+        "dompurify": "^3.4.14",
         "react": "18.3.1",
         "react-dom": "18.3.1"
       },
@@ -2139,6 +2140,13 @@
         "@types/react": "^18.0.0"
       }
     },
+    "node_modules/@types/trusted-types": {
+      "version": "2.0.7",
+      "resolved": "https://registry.npmjs.org/@types/trusted-types/-/trusted-types-2.0.7.tgz",
+      "integrity": "sha512-ScaPdn1dQczgbl0QFTeTOmVHFULt394XJgOQNoyVhZ6r2vLnMLJfBPd53SB52T/3G36VI1/g2MZaX0cwDuXsfw==",
+      "license": "MIT",
+      "optional": true
+    },
     "node_modules/@vitejs/plugin-react": {
       "version": "4.3.4",
       "resolved": "https://registry.npmjs.org/@vitejs/plugin-react/-/plugin-react-4.3.4.tgz",
@@ -2641,6 +2649,15 @@
       "license": "MIT",
       "peer": true
     },
+    "node_modules/dompurify": {
+      "version": "3.4.14",
+      "resolved": "https://registry.npmjs.org/dompurify/-/dompurify-3.4.14.tgz",
+      "integrity": "sha512-dVoH9z+MY+C9IilgGCk3YfFqjLi3fChm2OiKJMzh6axrJ5qwxqWaZamgmHrpv22CN/KdbZJuGEGgfQoL00LTdg==",
+      "license": "(MPL-2.0 OR Apache-2.0)",
+      "optionalDependencies": {
+        "@types/trusted-types": "^2.0.7"
+      }
+    },
     "node_modules/electron-to-chromium": {
       "version": "1.5.415",
       "resolved": "https://registry.npmjs.org/electron-to-chromium/-/electron-to-chromium-1.5.415.tgz",
diff --git a/package.json b/package.json
index e6bbfbb..7e3ec8c 100644
--- a/package.json
+++ b/package.json
@@ -12,29 +12,30 @@
     "lint:imports": "\"Speak-EPUB-1.0.0\\venv\\Scripts\\lint-imports.exe\""
   },
   "dependencies": {
-    "react": "18.3.1",
-    "react-dom": "18.3.1",
     "@tauri-apps/api": "^2.11.0",
     "@tauri-apps/plugin-shell": "^2.3.5",
-    "@tauri-apps/plugin-store": "^2.4.4"
+    "@tauri-apps/plugin-store": "^2.4.4",
+    "dompurify": "^3.4.14",
+    "react": "18.3.1",
+    "react-dom": "18.3.1"
   },
   "devDependencies": {
+    "@tailwindcss/vite": "4.1.13",
+    "@tauri-apps/cli": "2.11.4",
+    "@testing-library/jest-dom": "6.6.3",
+    "@testing-library/react": "16.3.0",
+    "@testing-library/user-event": "14.6.3",
+    "@types/node": "22.13.10",
     "@types/react": "18.3.12",
     "@types/react-dom": "18.3.7",
-    "@types/node": "22.13.10",
     "@vitejs/plugin-react": "4.3.4",
-    "typescript": "5.8.3",
-    "vite": "6.3.6",
-    "@tauri-apps/cli": "2.11.4",
-    "tailwindcss": "4.1.13",
-    "@tailwindcss/vite": "4.1.13",
-    "clsx": "2.1.1",
-    "tailwind-merge": "3.2.0",
     "class-variance-authority": "0.7.1",
-    "vitest": "3.2.4",
+    "clsx": "2.1.1",
     "jsdom": "26.1.0",
-    "@testing-library/react": "16.3.0",
-    "@testing-library/jest-dom": "6.6.3",
-    "@testing-library/user-event": "14.6.3"
+    "tailwind-merge": "3.2.0",
+    "tailwindcss": "4.1.13",
+    "typescript": "5.8.3",
+    "vite": "6.3.6",
+    "vitest": "3.2.4"
   }
 }
diff --git a/src-tauri/capabilities/default.json b/src-tauri/capabilities/default.json
index 804136f..cfcbfb8 100644
--- a/src-tauri/capabilities/default.json
+++ b/src-tauri/capabilities/default.json
@@ -1,22 +1,26 @@
 {
   "$schema": "../gen/schemas/desktop-schema.json",
   "identifier": "default",
-  "description": "Capability for the main window — shell + store + core events",
+  "description": "Capability for the main window — store + core events + scoped opener",
   "windows": ["main"],
   "permissions": [
     "core:default",
     "core:event:default",
     "core:event:allow-emit",
     "core:event:allow-listen",
-    "shell:default",
-    "shell:allow-open",
-    "shell:allow-spawn",
     "store:default",
     "store:allow-get",
     "store:allow-set",
     "store:allow-load",
     "store:allow-save",
     "opener:default",
-    "opener:allow-open-path"
+    {
+      "identifier": "opener:allow-open-path",
+      "allow": [
+        { "path": "**/*.epub" },
+        { "path": "**/output" },
+        { "path": "**/output/**" }
+      ]
+    }
   ]
 }
diff --git a/src/App.announcer.test.tsx b/src/App.announcer.test.tsx
index 63059e2..69d9dee 100644
--- a/src/App.announcer.test.tsx
+++ b/src/App.announcer.test.tsx
@@ -1,6 +1,5 @@
 import { describe, it, expect, vi, beforeEach } from "vitest";
 import { render, screen } from "@testing-library/react";
-import userEvent from "@testing-library/user-event";
 
 const mockGetFilters = vi.fn();
 const mockCallSidecar = vi.fn();
diff --git a/src/components/Preview.test.tsx b/src/components/Preview.test.tsx
index 40d4a3c..bcc6805 100644
--- a/src/components/Preview.test.tsx
+++ b/src/components/Preview.test.tsx
@@ -161,4 +161,60 @@ describe("Preview 2.2 — selector boundary + live re-parse", () => {
     fireEvent.click(screen.getByTestId("preview-overlay"));
     expect(onClose).toHaveBeenCalled();
   });
+
+  it("sanitizes onerror payload in rendered Cleaned tab", async () => {
+    mockPreviewChapter.mockResolvedValue({
+      id: "1",
+      result: {
+        url: "https://www.novelphoenix.com/novel/123/chapter/42",
+        originalHtml: "<html>raw</html>",
+        originalText: "raw",
+        html: '<p>clean body</p><img src=x onerror="alert(1)">',
+        text: "clean body",
+        start: "div#chapter-content",
+        end: null,
+      },
+    });
+    render(<Preview open={true} onClose={vi.fn()} chapterUrl="https://www.novelphoenix.com/novel/123/chapter/42" chapterTitle="T" chapterIndex={1} />);
+    await vi.advanceTimersByTimeAsync(350);
+    const rendered = screen.getByTestId("preview-rendered");
+    const img = rendered.querySelector("img");
+    expect(img).not.toBeNull();
+    expect(img?.hasAttribute("onerror")).toBe(false);
+    // clean content still renders after sanitization
+    expect(rendered.textContent).toContain("clean body");
+  });
+
+  it("sanitizes onerror payload in rendered Original tab", async () => {
+    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
+    mockPreviewChapter.mockResolvedValue({
+      id: "1",
+      result: {
+        url: "https://www.novelphoenix.com/novel/123/chapter/42",
+        originalHtml: '<p>raw body</p><img src=x onerror="alert(1)" onclick="steal()">',
+        originalText: "raw body",
+        html: "<div>cleaned</div>",
+        text: "cleaned",
+        start: "div#chapter-content",
+        end: null,
+      },
+    });
+    render(<Preview open={true} onClose={vi.fn()} chapterUrl="https://www.novelphoenix.com/novel/123/chapter/42" chapterTitle="T" chapterIndex={1} />);
+    await vi.advanceTimersByTimeAsync(350);
+    await user.click(screen.getByTestId("preview-tab-original"));
+    const rendered = screen.getByTestId("preview-rendered");
+    const img = rendered.querySelector("img");
+    expect(img).not.toBeNull();
+    expect(img?.hasAttribute("onerror")).toBe(false);
+    expect(img?.hasAttribute("onclick")).toBe(false);
+    expect(rendered.textContent).toContain("raw body");
+  });
+
+  it("clean content still renders after sanitize in default Cleaned tab", async () => {
+    render(<Preview open={true} onClose={vi.fn()} chapterUrl="https://www.novelphoenix.com/novel/123/chapter/42" chapterTitle="T" chapterIndex={1} />);
+    await vi.advanceTimersByTimeAsync(350);
+    const rendered = screen.getByTestId("preview-rendered");
+    expect(rendered.textContent).toContain("cleaned");
+    expect(rendered.querySelector("div")).not.toBeNull();
+  });
 });
diff --git a/src/components/Preview.tsx b/src/components/Preview.tsx
index dbf15bf..2fbc9b5 100644
--- a/src/components/Preview.tsx
+++ b/src/components/Preview.tsx
@@ -1,4 +1,5 @@
 import { useEffect, useRef, useState } from "react";
+import DOMPurify from "dompurify";
 import { previewChapter, getSelectors, saveSelectors, clearSelectors, isPreviewResult } from "@/lib/sidecar";
 
 type PreviewProps = {
@@ -421,9 +422,9 @@ export default function Preview({ open, onClose, chapterUrl, chapterTitle, chapt
             <div className="border-b bg-muted/20 px-4 py-2 text-body-sm font-medium text-muted-foreground">Podgląd renderowany</div>
             <div className="prose prose-sm max-w-none p-4 text-body" data-testid="preview-rendered">
               {tab === "original" ? (
-                <div dangerouslySetInnerHTML={{ __html: originalHtml.slice(0, 20000) }} />
+                <div dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(originalHtml.slice(0, 20000)) }} />
               ) : (
-                <div dangerouslySetInnerHTML={{ __html: (removedCount > 0 ? filteredHtml : cleanedHtml).slice(0, 20000) }} />
+                <div dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize((removedCount > 0 ? filteredHtml : cleanedHtml).slice(0, 20000)) }} />
               )}
             </div>
           </div>


Do not invoke any skill. Return only the review result.
