"""
adapters/novelphoenix.py — ScraperPort impl for NovelPhoenix (Epic 1.2).

Implements search / listChapters / fetchChapter over requests+BeautifulSoup
with polite adapter-local _get, selectors owned by adapter, heuristic fallback,
sequential fetch only, spine-order 1..N, dedupe, cover via og:image.
"""
from __future__ import annotations

import re
import threading
from typing import List
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup

from core.ports import AdapterError, ChapterContent, ChapterInfo, ScraperPort, SearchResult, Selectors

from ._http import _get

BASE = "https://www.novelphoenix.com"


class NovelPhoenixAdapter(ScraperPort):
    """NovelPhoenix adapter — selectors + heuristic fallback owned by adapter (AD-5/AD-7)."""

    # exposed for tests to inspect last cover seen in listChapters
    _last_cover_url: str | None = None
    _lock = threading.Lock()

    # ------------------------------------------------------------------ search
    def search(self, title: str) -> List[SearchResult]:
        # Validation: empty/whitespace => ValueError without network
        if not isinstance(title, str) or not title.strip():
            raise ValueError("title must be non-empty")
        # Truncate len>300 to 200 before request (spec)
        if len(title) > 300:
            title = title[:200]
        # Build search URL
        keyword = quote(title)
        url = f"{BASE}/search?keyword={keyword}"
        try:
            resp = _get(url, timeout=12, retries=2)
        except Exception as e:
            # 4xx/5xx/timeout after 2 retries → [] + log "search failed <site>: <code>" no raise
            # need to extract code if HTTPError
            code = ""
            if isinstance(e, requests.exceptions.HTTPError) and e.response is not None:
                code = str(e.response.status_code)
            elif isinstance(e, requests.exceptions.Timeout):
                code = "timeout"
            elif e.args:
                code = str(e.args[0])[:80]
            print(f"search failed novelphoenix.com: {code or e}")
            return []

        soup = BeautifulSoup(resp.text or "", "lxml")
        results: List[SearchResult] = []
        items = soup.select("div.book-item")
        # fallback: if no book-item, try alternative generic container?
        # Keep strict to spec; if empty, return []
        for item in items:
            a = item.select_one("a[href]")
            if a is None:
                continue
            href = a.get("href")
            if not href:
                continue
            if href.strip().lower().startswith(("javascript:", "mailto:", "data:")):
                continue
            abs_url = urljoin(BASE, href)
            # title non-empty
            title_text = a.get_text(strip=True)
            if not title_text:
                # try alternative title selectors inside item
                alt = item.select_one(".title, .book-name, h3, h2, .name")
                if alt:
                    title_text = alt.get_text(strip=True)
            if not title_text:
                title_text = (a.get("title") or "").strip()
            if not title_text:
                continue
            # chapter_count via regex (\d+) or None from span.chapters
            chapter_count = None
            span = item.select_one("span.chapters")
            if span is not None:
                m = re.search(r"(\d+)", span.get_text())
                if m:
                    try:
                        chapter_count = int(m.group(1))
                    except ValueError:
                        chapter_count = None
            # fallback: if no span, keep None (spec says via regex (\d+) or None)
            # cover_url - try img inside item
            cover_url = None
            img = item.select_one("img")
            if img is not None:
                src = img.get("src") or img.get("data-src") or img.get("data-original")
                if src and src.strip() and not src.strip().lower().startswith("data:"):
                    cover_url = urljoin(BASE, src.strip())
            # author optional
            author = None
            author_el = item.select_one(".author, span.author, a.author")
            if author_el is not None:
                txt = author_el.get_text(strip=True)
                author = txt or None

            results.append(
                SearchResult(
                    site="novelphoenix.com",
                    title=title_text,
                    url=abs_url,
                    chapter_count=chapter_count,
                    author=author,
                    cover_url=cover_url,
                )
            )
        return results

    # --------------------------------------------------------------- listChapters
    def listChapters(self, url: str) -> List[ChapterInfo]:
        if not isinstance(url, str) or not url.strip():
            raise ValueError("url must be non-empty")
        # Sequential fetch only; use _get with retries
        try:
            resp = _get(url, timeout=12, retries=2)
        except requests.exceptions.HTTPError as e:
            # 404/timeout → AdapterError LIST_FAILED; 5xx already retried
            raise AdapterError(f"LIST_FAILED: {url} {e}", code="LIST_FAILED") from e
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            raise AdapterError(f"LIST_FAILED: timeout {url} {e}", code="LIST_FAILED") from e
        except Exception as e:
            raise AdapterError(f"LIST_FAILED: {e}", code="LIST_FAILED") from e

        soup = BeautifulSoup(resp.text or "", "lxml")

        # cover via og:image fallback img.cover
        cover_url = None
        og = soup.select_one('meta[property="og:image"]')
        if og is not None and og.get("content"):
            content = og.get("content")
            if content and content.strip():
                cover_url = urljoin(url, content.strip())
        if cover_url is None:
            img_cover = soup.select_one("img.cover")
            if img_cover is not None:
                src = img_cover.get("src") or img_cover.get("data-src") or img_cover.get("data-original")
                if src and src.strip() and not src.strip().lower().startswith("data:"):
                    cover_url = urljoin(url, src.strip())
        # expose for test inspection and for future cover handling
        with self._lock:
            self._last_cover_url = cover_url

        # chapter anchors: ul.chapter-list li a  OR  a[href*=/chapter/] dedupe/normalize
        anchors: List = []
        chap_list = soup.select("ul.chapter-list li a[href]")
        if chap_list:
            anchors = list(chap_list)
            # also consider fallback anchors not in list? spec says dedupe, so include both
            # Add fallback anchors that are not already in chap_list
            fallback = soup.select("a[href*='/chapter/']")
            # deduplicate by href for this merge step (preserve order)
            existing_hrefs = {a.get("href") for a in anchors}
            for a in fallback:
                if a.get("href") not in existing_hrefs:
                    anchors.append(a)
        else:
            anchors = soup.select("a[href*='/chapter/']")
            # broader fallback if site uses different pattern
            if not anchors:
                anchors = soup.select("a[href*='chapter']")

        seen: set[str] = set()
        collected: List[tuple[str, str]] = []
        for a in anchors:
            href = a.get("href")
            if not href:
                continue
            if href.strip().lower().startswith(("javascript:", "mailto:", "data:")):
                continue
            abs_url = urljoin(url, href)
            # normalize for dedupe: strip fragment, strip query for test stability, rstrip slash
            normalized = abs_url.split("#")[0].split("?")[0].rstrip("/")
            if normalized in seen:
                continue
            title = a.get_text(strip=True)
            # skip len<2 or ^(next|prev|cover|previous)$ (case-insensitive)
            if len(title) < 2:
                continue
            if re.match(r"^(next|prev|cover|previous)$", title, re.I):
                continue
            seen.add(normalized)
            collected.append((normalized, title))

        if not collected:
            return []

        # 1..N spine order contiguous, url absolute via urljoin already
        result: List[ChapterInfo] = []
        for idx, (u, t) in enumerate(collected, 1):
            result.append(ChapterInfo(index=idx, title=t, url=u))
        return result

    # --------------------------------------------------------------- fetchChapter
    def fetchChapter(self, url: str) -> ChapterContent:
        if not isinstance(url, str) or not url.strip():
            raise ValueError("url must be non-empty")
        try:
            resp = _get(url, timeout=12, retries=2)
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            if status == 404:
                raise AdapterError(f"FETCH_FAILED: 404 {url}", code="FETCH_FAILED") from e
            # 429/5xx already retried
            raise AdapterError(f"FETCH_FAILED: {e}", code="FETCH_FAILED") from e
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            raise AdapterError(f"FETCH_FAILED: timeout {url} {e}", code="FETCH_FAILED") from e
        except Exception as e:
            raise AdapterError(f"FETCH_FAILED: {e}", code="FETCH_FAILED") from e

        soup = BeautifulSoup(resp.text or "", "lxml")
        # title extraction
        title_tag = soup.find(["h1", "h2", "h3"])
        raw_title = title_tag.get_text(strip=True) if title_tag else ""
        title = raw_title if raw_title else url

        selectors = self.getSelectors()
        target = None
        html = ""
        text = ""
        if selectors.start:
            try:
                target = soup.select_one(selectors.start)
            except Exception:
                target = None
        if target is not None:
            for tag in target(["script", "style", "nav", "aside"]):
                tag.decompose()
            html = str(target)
            text = target.get_text(separator=" ", strip=True)
            text = re.sub(r"\s+", " ", text).strip()
            if not text:
                target = None
        if target is None:
            # heuristic fallback: article/#content/.chapter-content
            heuristic = None
            for sel in ["article", "#content", ".chapter-content", "#chapter-content", ".content", "#chapters"]:
                try:
                    heuristic = soup.select_one(sel)
                    if heuristic is not None:
                        break
                except Exception:
                    continue
            if heuristic is not None:
                for tag in heuristic(["script", "style", "nav", "aside"]):
                    tag.decompose()
                html = str(heuristic)
                text = heuristic.get_text(separator=" ", strip=True)
                text = re.sub(r"\s+", " ", text).strip()
            else:
                # fallback whole body
                for tag in soup(["script", "style", "nav", "aside"]):
                    tag.decompose()
                body = soup.body or soup
                html = str(body)
                text = body.get_text(separator=" ", strip=True)
                text = re.sub(r"\s+", " ", text).strip()

        return ChapterContent(url=url, title=title, html=html, text=text)

    # --------------------------------------------------------------- getSelectors
    def getSelectors(self) -> Selectors:
        return Selectors(start="div#chapter-content", end=None)
