"""
adapters/novelphoenix.py — ScraperPort impl for NovelPhoenix (Epic 1.2).

Implements search / listChapters / fetchChapter over requests+BeautifulSoup
with polite adapter-local _get, selectors owned by adapter, heuristic fallback,
sequential fetch only, spine-order 1..N, dedupe, cover via og:image.
"""
from __future__ import annotations

import re
import threading
import time
from typing import List
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup

from core.ports import AdapterError, ChapterContent, ChapterInfo, ScraperPort, SearchResult, Selectors

from ._http import _get

BASE = "https://www.novelphoenix.com"


def _extract_cover(soup: BeautifulSoup, page_url: str) -> str | None:
    """Cover via og:image fallback img.cover (shared by list/fetch paths)."""
    cover_url = None
    og = soup.select_one('meta[property="og:image"]')
    if og is not None and og.get("content"):
        content = og.get("content")
        if content and content.strip():
            cover_url = urljoin(page_url, content.strip())
    if cover_url is None:
        img_cover = soup.select_one("img.cover")
        if img_cover is not None:
            src = img_cover.get("src") or img_cover.get("data-src") or img_cover.get("data-original")
            if src and src.strip() and not src.strip().lower().startswith("data:"):
                cover_url = urljoin(page_url, src.strip())
    return cover_url


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
    # Chapter-index pagination cap so a misbehaving site cannot spin forever.
    _MAX_INDEX_PAGES = 200
    # Link captions that point at a chapter but are not chapter titles.
    _NOISE_TITLE_RE = re.compile(
        r"^(next|prev|previous|cover|first|last|read now|read first|read latest)$", re.I
    )
    _CHAPTER_NUM_HREF_RE = re.compile(r"/chapter-(\d+)(?:[/?#].*)?$")
    _CHAPTER_NUM_SLASH_RE = re.compile(r"/chapter/(\d+)(?:[/?#].*)?$")
    _NOVEL_FROM_CHAPTER_URL_RE = re.compile(
        r"^(?P<novel>https?://[^/]+/novel/[^/?#]+?)/chapter-\d+(?:[/?#].*)?$", re.I
    )

    @staticmethod
    def _chapter_num_of(u: str) -> int:
        m = NovelPhoenixAdapter._CHAPTER_NUM_HREF_RE.search(u) or NovelPhoenixAdapter._CHAPTER_NUM_SLASH_RE.search(u)
        return int(m.group(1)) if m else 10**9

    @classmethod
    def _normalize_novel_url(cls, url: str) -> str:
        """Accept a pasted chapter URL (…/novel/<slug>/chapter-57) and return the novel URL."""
        u = url.strip().rstrip("/")
        m = cls._NOVEL_FROM_CHAPTER_URL_RE.match(u)
        return m.group("novel") if m else u

    def listChapters(self, url: str) -> List[ChapterInfo]:
        if not isinstance(url, str) or not url.strip():
            raise ValueError("url must be non-empty")
        # Pasted chapter links resolve to the whole novel's chapter list.
        url = self._normalize_novel_url(url)
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

        # cover via og:image fallback img.cover (shared helper)
        cover_url = _extract_cover(soup, url)
        # expose for test inspection and for future cover handling
        with self._lock:
            self._last_cover_url = cover_url

        seen: set[str] = set()
        collected: List[tuple[str, str]] = []  # (absolute chapter url, title)

        def _harvest(soup_obj: BeautifulSoup) -> int:
            """Collect /chapter-N links (index pages list the latest chapter first)."""
            added = 0
            for a in soup_obj.select("a[href]"):
                href = (a.get("href") or "").strip()
                if not href or href.lower().startswith(("javascript:", "mailto:", "data:")):
                    continue
                m = self._CHAPTER_NUM_HREF_RE.search(href) or self._CHAPTER_NUM_SLASH_RE.search(href)
                if not m:
                    continue
                title = (a.get("title") or "").strip()
                if not title:
                    title = a.get_text(strip=True)
                if self._NOISE_TITLE_RE.match(title or ""):
                    continue
                if not title or len(title) < 2:
                    title = f"Chapter {int(m.group(1))}"
                abs_url = urljoin(url, href.split("#")[0]).split("?")[0].rstrip("/")
                if abs_url in seen:
                    continue
                seen.add(abs_url)
                collected.append((abs_url, title))
                added += 1
            return added

        # Preferred path: dedicated paginated chapter index (e.g. <novel>/chapters?page=N).
        index_url: str | None = None
        if re.search(r"/chapters(?:[/?#].*)?$", url, re.I):
            index_url = url
        else:
            link = soup.select_one("a[href*='/chapters']")
            if link is not None:
                href = (link.get("href") or "").strip()
                if href and not href.lower().startswith(("javascript:", "mailto:", "data:")):
                    candidate = urljoin(url, href).split("#")[0]
                    if re.search(r"/chapters(?:[/?#].*)?$", candidate, re.I):
                        index_url = candidate

        if index_url is not None:
            page_url: str | None = index_url
            page_num = 1
            max_page = 1
            while page_url is not None and page_num <= self._MAX_INDEX_PAGES:
                try:
                    page_resp = _get(page_url, timeout=12, retries=2)
                except Exception as e:
                    # a partially harvested index is still useful; fail only with nothing
                    if page_num == 1:
                        raise AdapterError(f"LIST_FAILED: {e}", code="LIST_FAILED") from e
                    break
                page_soup = BeautifulSoup(page_resp.text or "", "lxml")
                _harvest(page_soup)
                next_url: str | None = None
                for a in page_soup.select("a[href*='page=']"):
                    href = (a.get("href") or "").split("#")[0]
                    m = re.search(r"[?&]page=(\d+)", href)
                    if not m:
                        continue
                    n = int(m.group(1))
                    if n > max_page:
                        max_page = n
                    if n == page_num + 1 and next_url is None:
                        next_url = urljoin(page_url, href)
                if next_url is None or page_num >= max_page:
                    break
                time.sleep(0.3)  # light politeness between index pages
                page_url = next_url
                page_num += 1

            # Spine order = chapter number (page 1 lists the latest chapter first).
            collected.sort(key=lambda t: self._chapter_num_of(t[0]))

        else:
            # Legacy single-page parse: ul.chapter-list li a OR a[href*=/chapter/]
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
                # skip len<2 or generic CTA captions (case-insensitive)
                if len(title) < 2:
                    continue
                if self._NOISE_TITLE_RE.match(title):
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
        # title extraction — keep outside clean (not selector-dependent)
        title_tag = soup.find(["h1", "h2", "h3"])
        raw_title = title_tag.get_text(strip=True) if title_tag else ""
        title = raw_title if raw_title else url

        # remember page cover for single-chapter flows (same pattern as listChapters)
        # and carry it on the DTO so fetch cache hits keep it too
        page_cover: str | None = None
        try:
            page_cover = _extract_cover(soup, url)
            with self._lock:
                self._last_cover_url = page_cover
        except Exception:
            page_cover = None

        # delegate isolation to Core clean.py via dynamic import (AD-1 linter exception)
        try:
            import importlib as _il

            _mod = _il.import_module("core.clean")
            resolve_selectors = getattr(_mod, "resolve_selectors")
            clean_html = getattr(_mod, "clean_html")
            selectors = resolve_selectors(self)
            html, text = clean_html(resp.text or "", selectors.start, selectors.end)
        except ValueError as ve:
            # invalid selector from override — fallback to heuristic/body via clean_html with None
            try:
                import importlib as _il2

                _mod2 = _il2.import_module("core.clean")
                clean_html2 = getattr(_mod2, "clean_html")
                html, text = clean_html2(resp.text or "", None, None)
            except Exception:
                # ultimate fallback: heuristic inline
                for tag in soup(["script", "style", "nav", "aside"]):
                    tag.decompose()
                body = soup.body or soup
                html = str(body)
                text = body.get_text(separator=" ", strip=True)
                text = re.sub(r"\s+", " ", text).strip()
        except Exception:
            # fallback heuristic inline if clean module missing
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
                    for tag in soup(["script", "style", "nav", "aside"]):
                        tag.decompose()
                    body = soup.body or soup
                    html = str(body)
                    text = body.get_text(separator=" ", strip=True)
                    text = re.sub(r"\s+", " ", text).strip()

        try:
            cover_out = page_cover if isinstance(page_cover, str) and page_cover.strip() else None
        except Exception:
            cover_out = None
        return ChapterContent(url=url, title=title, html=html, text=text, cover_url=cover_out)

    # --------------------------------------------------------------- getSelectors
    def getSelectors(self) -> Selectors:
        return Selectors(start="div#chapter-content", end=None)
