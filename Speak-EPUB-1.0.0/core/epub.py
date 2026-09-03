"""
core/epub.py — EPUB assembly gate (Story 2.4).
AD-8: EPUB is intermediate invariant feeding TTS. AD-2: filter once after clean.
AD-9: cache owned by core/fetch, raw never filtered.
Pure module — no adapter imports, keeps GUI->Core->Port->Adapter.
"""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

# ---------------------------------------------------------------------------
# sanitize_filename — mirror speak.py:84
# ---------------------------------------------------------------------------

def sanitize_filename(value: str, fallback: str = "chapter", max_len: int = 60) -> str:
    """
    Mirror speak.py:84 sanitize_filename.
    - replace [\\/:*?"<>|] with _
    - collapse whitespace
    - truncate max_len
    - fallback if empty or only underscores/dots
    """
    if not isinstance(value, str):
        value = str(value) if value is not None else ""
    safe = re.sub(r'[\\/:*?"<>|]', "_", value).strip()
    safe = re.sub(r"\s+", " ", safe).strip()
    safe = safe[:max_len].strip()
    if not safe:
        return fallback
    # fallback if safe contains only underscores/dots/spaces (e.g., "///" -> "___")
    stripped = safe.strip("_. ")
    if not stripped:
        return fallback
    return safe


def _slug_from_title(title: str | None, fallback: str = "book") -> str:
    """Slug for epub filename, max 60 chars, fallback."""
    if not title or not isinstance(title, str) or not title.strip():
        return fallback
    # use sanitize_filename with max 60
    slug = sanitize_filename(title.strip(), fallback=fallback, max_len=60)
    # also replace consecutive underscores? keep as is per speak.py
    if not slug.strip():
        return fallback
    return slug


# ---------------------------------------------------------------------------
# run_epubcheck — via shutil.which("epubcheck") else ebooklib proxy
# ---------------------------------------------------------------------------

def run_epubcheck(epub_path: Path | str) -> Tuple[bool, List[str]]:
    """
    Run epubcheck if available, else fallback to ebooklib proxy.
    Returns (ok, messages)
    """
    p = Path(epub_path)
    messages: List[str] = []
    # Try epubcheck binary
    epubcheck_bin = shutil.which("epubcheck")
    try:
        from core.tts import subprocess_kwargs
    except Exception:
        def subprocess_kwargs():  # type: ignore[no-redef]
            return {}
    if epubcheck_bin:
        try:
            result = subprocess.run(
                [epubcheck_bin, str(p)],
                capture_output=True,
                text=True,
                timeout=30,
                **subprocess_kwargs(),
            )
            out = (result.stdout or "") + (result.stderr or "")
            lines = [l for l in out.splitlines() if l.strip()]
            messages.extend(lines)
            ok = result.returncode == 0
            if ok and not messages:
                messages.append("epubcheck clean")
            return ok, messages
        except Exception as e:
            messages.append(f"epubcheck error: {e}")
            # fall through to proxy
    # Try java -jar epubcheck.jar if java exists
    java_bin = shutil.which("java")
    if java_bin:
        for cand in [Path("epubcheck.jar"), Path("tools/epubcheck.jar"), Path("Speak-EPUB-1.0.0/tools/epubcheck.jar")]:
            if cand.is_file():
                try:
                    result = subprocess.run(
                        [java_bin, "-jar", str(cand), str(p)],
                        capture_output=True,
                        text=True,
                        timeout=30,
                        **subprocess_kwargs(),
                    )
                    out = (result.stdout or "") + (result.stderr or "")
                    lines = [l for l in out.splitlines() if l.strip()]
                    messages.extend(lines)
                    ok = result.returncode == 0
                    if ok and not messages:
                        messages.append("epubcheck clean")
                    return ok, messages
                except Exception as e:
                    messages.append(f"java epubcheck error: {e}")
                    break
    # Fallback ebooklib proxy
    try:
        import ebooklib
        from ebooklib import epub as epub_lib

        book = epub_lib.read_epub(str(p))
        # basic spine check
        if not getattr(book, "spine", None):
            return False, ["ebooklib proxy: empty spine", "epubcheck (~) proxy"]
        # Try to read each item
        try:
            for item in book.get_items():
                try:
                    _ = item.get_content()
                except Exception as e:
                    return False, [f"ebooklib proxy: item read failed {e}", "epubcheck (~) proxy"]
        except Exception as e:
            return False, [f"ebooklib proxy iteration failed {e}"]
        # If we reach here, consider proxy clean
        # messages indicate proxy used
        msgs = ["epubcheck not found — using ebooklib proxy", "proxy clean"]
        return True, msgs
    except Exception as e:
        return False, [f"ebooklib proxy failed: {e}"]


# ---------------------------------------------------------------------------
# Helper: atomic write helper
# ---------------------------------------------------------------------------

def _atomic_write_epub(book, output_path: Path) -> None:
    """Write epub atomically via tmp.replace"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_suffix(output_path.suffix + ".tmp")
    # ebooklib writes directly; we write to tmp then replace
    import ebooklib
    from ebooklib import epub as epub_lib

    epub_lib.write_epub(str(tmp), book)
    tmp.replace(output_path)


# ---------------------------------------------------------------------------
# Chapter image embedding — remote <img> becomes local items (Story 2.4 images).
# AD-8: EPUB must be self-contained; remote http(s) images break offline
# readers, so download + embed best-effort. Offline-safe: any failure keeps
# the original remote URL and only logs.
# ---------------------------------------------------------------------------

_IMAGE_EXT_BY_CTYPE = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/svg+xml": "svg",
    "image/bmp": "bmp",
}

_MAX_IMAGE_BYTES = 8 * 1024 * 1024
_MAX_IMAGES_PER_CHAPTER = 20


def _download_image(url: str, timeout: float = 10.0):
    """Download one image. Returns (data, ext) or None on any failure."""
    try:
        import requests
    except Exception:
        return None
    try:
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": "SpeakEPUB/1.0"}, stream=True)
    except Exception:
        return None
    try:
        if resp.status_code != 200:
            return None
        ctype = (resp.headers.get("Content-Type", "") or "").lower().split(";")[0].strip()
        ext = _IMAGE_EXT_BY_CTYPE.get(ctype)
        if ext is None:
            return None
        chunks: list[bytes] = []
        total = 0
        for chunk in resp.iter_content(256 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > _MAX_IMAGE_BYTES:
                return None
            chunks.append(chunk)
        data = b"".join(chunks)
        if not data:
            return None
        return data, ext
    except Exception:
        return None
    finally:
        try:
            resp.close()
        except Exception:
            pass


def embed_chapter_images(cleaned_html: str, page_url: str, chapter_idx: int, download=None, max_images: int = _MAX_IMAGES_PER_CHAPTER):
    """Embed remote chapter <img> as local EPUB items.

    - Only http(s) src (data: already embedded; relative resolved via page_url).
    - On success rewrites src to images/chNNN_MM.ext and drops remote-only
      srcset/sizes; on any failure the original src is kept.
    - Never raises for bad images; returns (html, items, embedded, skipped)
      where items are (uid, file_name, media_type, data) tuples for the caller
      to add as EpubImage. `download` is injectable for tests.
    """
    items: List[Tuple[str, str, str, bytes]] = []
    if not cleaned_html or not cleaned_html.strip():
        return cleaned_html or "", items, 0, 0
    try:
        from bs4 import BeautifulSoup
    except Exception:
        return cleaned_html, items, 0, 0
    try:
        from urllib.parse import urljoin, urlparse
    except Exception:
        return cleaned_html, items, 0, 0

    fetch = download or _download_image
    try:
        soup = BeautifulSoup(cleaned_html, "lxml")
    except Exception:
        return cleaned_html, items, 0, 0
    body = soup.body if soup.body else soup
    imgs = body.find_all("img")
    if not imgs:
        return cleaned_html, items, 0, 0

    embedded = 0
    skipped = 0
    for img in imgs:
        if embedded >= max_images:
            break
        try:
            src = img.get("src") or ""
        except Exception:
            skipped += 1
            continue
        if not isinstance(src, str) or not src.strip():
            skipped += 1
            continue
        src = src.strip()
        if src.lower().startswith("data:"):
            continue  # already embedded
        try:
            abs_url = urljoin(page_url, src)
            scheme = urlparse(abs_url).scheme.lower()
        except Exception:
            skipped += 1
            continue
        if scheme not in ("http", "https"):
            skipped += 1
            continue
        try:
            got = fetch(abs_url)
        except Exception:
            got = None
        if not got:
            skipped += 1
            continue
        data, ext = got
        if not data:
            skipped += 1
            continue
        n = embedded + 1
        uid = f"img_{chapter_idx:03d}_{n:02d}"
        file_name = f"images/ch{chapter_idx:03d}_{n:02d}.{ext}"
        subtype = {"jpg": "jpeg", "svg": "svg+xml"}.get(ext, ext)
        media_type = f"image/{subtype}"
        try:
            img["src"] = file_name
            # remote-only variant attributes must go (they point at remote files)
            for attr in ("srcset", "sizes", "data-src", "data-original", "data-srcset"):
                try:
                    if attr in img.attrs:
                        del img.attrs[attr]
                except Exception:
                    pass
        except Exception:
            skipped += 1
            continue
        items.append((uid, file_name, media_type, data))
        embedded += 1

    if not embedded:
        return cleaned_html, items, 0, skipped
    try:
        if soup.body:
            html = "".join(str(c) for c in soup.body.contents) if soup.body.contents else ""
        else:
            html = str(soup)
    except Exception:
        return cleaned_html, items, 0, skipped
    return html, items, embedded, skipped


# ---------------------------------------------------------------------------
# build_epub — core gate
# ---------------------------------------------------------------------------

def build_epub(
    novel_url: str,
    from_idx: int | None = None,
    to_idx: int | None = None,
    title: str | None = None,
    author: str | None = None,
    cover_url: str | None = None,
    output_dir: str | Path | None = None,
    filters: List[Dict[str, Any]] | None = None,
    cache_dir: str | Path | None = None,
    chapter_urls: List[str] | None = None,
    start_selector: str | None = None,
    end_selector: str | None = None,
    extra_params: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    Build validated EPUB offline from cached raw.html.

    - Validate novel_url ^https?:// else VALUE_ERROR
    - Clamp from/to to 1.. large (1..100000) and swap if inverted
    - offline cache-only read_cache per chapter (no network fallback except cover)
    - resolve_selectors -> clean_html -> apply_filters once
    - Assemble EpubBook with cover/TOC, write atomically, run_epubcheck
    - Return {path,size,chapter_count,epubcheck_ok,messages,logs}

    chapter_urls: if provided, used directly in order; else derived via
                  _CHAPTER_CACHE or synthetic fallback.
    start_selector/end_selector: optional override for cleaning.
    """
    import importlib

    # Validate novel_url
    if not isinstance(novel_url, str) or not novel_url.strip():
        raise ValueError("url must be non-empty")
    novel_url = novel_url.strip()
    if not re.match(r"^https?://", novel_url, re.I):
        raise ValueError("url must be http(s)")
    try:
        from urllib.parse import urlparse

        parsed = urlparse(novel_url)
        host = (parsed.hostname or "").lower().rstrip(".")
        if not host:
            raise ValueError("url must contain host")
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(str(e)) from e

    # Sanitize title/author
    if title is not None:
        if not isinstance(title, str):
            title = str(title)
        title = title.strip()
        if len(title) > 200:
            title = title[:200]
        if not title:
            title = None
    if author is not None:
        if not isinstance(author, str):
            author = str(author)
        author = author.strip()
        if len(author) > 200:
            author = author[:200]
        if not author:
            author = None

    # Cover url sanitization
    if cover_url is not None:
        if not isinstance(cover_url, str) or not cover_url.strip():
            cover_url = None
        else:
            cover_url = cover_url.strip()
            # allow http(s) and data: only; else discard?
            # For file writing, we only fetch http(s); data: we could decode but skip
            if cover_url.lower().startswith("data:"):
                # data-url guard: keep but skip fetch (treated as missing cover)
                # To avoid fetching, we treat as None for cover embedding, but keep sanitized
                pass
            elif not re.match(r"^https?://", cover_url, re.I):
                cover_url = None
            elif len(cover_url) > 500:
                cover_url = cover_url[:500]

    # Parse from/to
    def _to_int(v, default=None):
        if v is None or v == "":
            return default
        try:
            iv = int(v)  # type: ignore
            if iv < 1:
                return 1
            return max(1, min(iv, 100000))
        except Exception:
            return default

    from_i = _to_int(from_idx, 1)
    to_i = _to_int(to_idx, None)
    if from_i is None:
        from_i = 1
    if to_i is None:
        # if not provided, assume single chapter or to = from
        to_i = from_i
    # swap if inverted
    if from_i > to_i:
        from_i, to_i = to_i, from_i
    # clamp log handling will be done by caller; here just ensure 1..100000
    # If N known via chapter_urls length, we could clamp to N, but caller handles
    # Still ensure from/to within 1..100000
    from_i = max(1, min(from_i, 100000))
    to_i = max(1, min(to_i, 100000))

    # Load filters if not provided: try to load from store dynamically
    if filters is None:
        try:
            cfg_mod = importlib.import_module("core.config")
            load_store = getattr(cfg_mod, "load_store")
            store = load_store()
            raw_filters = store.get("filters", [])
            filt_mod = importlib.import_module("core.filters")
            sanitize = getattr(filt_mod, "sanitize_filters")
            filters = sanitize(raw_filters)
        except Exception:
            filters = []
    else:
        # sanitize provided filters
        try:
            filt_mod2 = importlib.import_module("core.filters")
            sanitize2 = getattr(filt_mod2, "sanitize_filters")
            filters = sanitize2(filters)
        except Exception:
            # fallback: keep as is if sanitize fails
            pass

    # Resolve output dir
    if output_dir is None or (isinstance(output_dir, str) and not output_dir.strip()):
        # canonical fallback: ./output under repo root if not supplied
        # Use cwd / output
        out_base = Path("output")
    else:
        out_base = Path(output_dir)
    out_base = Path(out_base)
    # If output_dir is file-like? ensure directory
    # out_base is directory for epub file

    # Slug and filename
    slug = _slug_from_title(title, fallback="book")
    filename = f"{slug}_chapters_{from_i:03d}_to_{to_i:03d}.epub"
    output_path = out_base / filename

    # Determine desired chapter urls
    desired_urls: List[str] = []
    if chapter_urls is not None and isinstance(chapter_urls, (list, tuple)) and len(chapter_urls) > 0:
        # use provided list, trim and filter
        cleaned_urls: List[str] = []
        for u in chapter_urls:  # type: ignore
            if isinstance(u, str) and u.strip():
                cleaned_urls.append(u.strip())
            elif isinstance(u, dict):
                uu = u.get("url") or u.get("link") or u.get("href")
                if isinstance(uu, str) and uu.strip():
                    cleaned_urls.append(uu.strip())
        # dedup preserve order for building? keep as is but spec says dedup for fetch; for epub we keep dedup?
        desired_urls = list(dict.fromkeys(cleaned_urls))
        # If desired_urls length doesn't match from_to range, we keep as is
        # Adjust from_i/to_i to reflect actual count? But filename already uses from_i/to_i
        # If provided urls length differs, we will still use them; chapter_count = len(desired_urls)
        # For clamp: if urls provided, we should not re-clamp based on N, but ensure from/to reflect urls length?
        # Keep original from_i/to_i for filename, but chapter_count from urls length
    else:
        # Need to derive via _CHAPTER_CACHE or adapter or synthetic
        derived = False
        # Try _CHAPTER_CACHE first (offline warm)
        try:
            cfg_mod2 = importlib.import_module("core.config")
            cache_dict = getattr(cfg_mod2, "_CHAPTER_CACHE", {})
            normalize = getattr(cfg_mod2, "_normalize_cache_key")
            key = normalize(novel_url)
            if key in cache_dict:
                cached_list = cache_dict[key]
                # cached_list is list of dicts
                idx_to_url: Dict[int, str] = {}
                for item in cached_list:  # type: ignore
                    try:
                        if isinstance(item, dict):
                            idx = item.get("index")
                            url = item.get("url") or item.get("link")
                        else:
                            idx = getattr(item, "index", None)
                            url = getattr(item, "url", None)
                        if idx is None or url is None:
                            continue
                        idx_int = int(idx)
                        if isinstance(url, str) and url.strip():
                            idx_to_url[idx_int] = url.strip()
                    except Exception:
                        continue
                # Now collect for range
                for idx in range(from_i, to_i + 1):
                    if idx in idx_to_url:
                        desired_urls.append(idx_to_url[idx])
                    else:
                        # Missing index -> will cause CACHE_MISS later
                        desired_urls.append(f"{novel_url.rstrip('/')}/chapter/{idx}")
                derived = len(idx_to_url) > 0
        except Exception:
            pass

        if not derived or not desired_urls:
            # Try adapter.listChapters via dynamic import (may require network)
            try:
                mod = importlib.import_module("adapters.novelphoenix")
                Adapter = getattr(mod, "NovelPhoenixAdapter")
                adapter = Adapter()
                lst = adapter.listChapters(novel_url)
                if lst and isinstance(lst, (list, tuple)):
                    idx_to_url2: Dict[int, str] = {}
                    for ci in lst:  # type: ignore
                        try:
                            idx2 = getattr(ci, "index", None)
                            url2 = getattr(ci, "url", None)
                            if idx2 is not None and url2:
                                idx_to_url2[int(idx2)] = str(url2).strip()
                        except Exception:
                            continue
                    # Derive N for clamp if we have list
                    if idx_to_url2:
                        N = len(idx_to_url2)
                        # clamp from/to to 1..N if needed (if caller didn't)
                        # But we already clamped to 1..100000; now refine
                        orig_from, orig_to = from_i, to_i
                        from_i = max(1, min(from_i, N))
                        to_i = max(1, min(to_i, N))
                        if orig_from != from_i or orig_to != to_i:
                            # need to rebuild desired_urls with clamped range
                            desired_urls = []
                            for idx in range(from_i, to_i + 1):
                                if idx in idx_to_url2:
                                    desired_urls.append(idx_to_url2[idx])
                                else:
                                    desired_urls.append(f"{novel_url.rstrip('/')}/chapter/{idx}")
                            # update filename with clamped values
                            filename = f"{slug}_chapters_{from_i:03d}_to_{to_i:03d}.epub"
                            output_path = out_base / filename
                        else:
                            desired_urls = []
                            for idx in range(from_i, to_i + 1):
                                if idx in idx_to_url2:
                                    desired_urls.append(idx_to_url2[idx])
                                else:
                                    desired_urls.append(f"{novel_url.rstrip('/')}/chapter/{idx}")
                        derived = True
            except Exception:
                pass

        if not desired_urls:
            # Fallback synthetic
            for idx in range(from_i, to_i + 1):
                desired_urls.append(f"{novel_url.rstrip('/')}/chapter/{idx}")

    # At this point desired_urls length = chapter_count (to-from+1 or len provided)
    chapter_count = len(desired_urls)
    if chapter_count == 0:
        raise ValueError("no chapters to build")

    # -------------------------------------------------------------------
    # Offline cache check — fail fast if any missing
    # -------------------------------------------------------------------
    logs: List[str] = []
    missing: List[str] = []
    # dynamic import fetch
    try:
        fetch_mod = importlib.import_module("core.fetch")
        get_cache_path = getattr(fetch_mod, "get_cache_path")
        read_cache = getattr(fetch_mod, "read_cache")
    except Exception as e:
        raise ImportError(f"fetch module missing: {e}") from e

    # Check each desired url for cache presence
    for pos, url in enumerate(desired_urls):
        idx = from_i + pos if chapter_urls is None else pos + 1  # approximate for log
        # Use proper idx for log if we have mapping
        # Try to get actual idx from url map if available
        # For logging, use from_i + pos
        ch_num = from_i + pos
        # check cache
        try:
            cached = read_cache(url, cache_dir) if cache_dir is not None else read_cache(url)
        except Exception:
            cached = None
        if cached is None:
            missing.append(url)
            logs.append(f"cache miss chapter {ch_num} {url}")
        else:
            # ensure raw contains? we don't filter yet
            pass

    if missing:
        # Return error shape for caller to map to CACHE_MISS?
        # Raise custom exception with missing list
        # We use ValueError with code? Better raise AdapterError with code CACHE_MISS?
        # To allow handle_rpc to catch and return CACHE_MISS, we raise an exception with attribute code
        from core.ports import AdapterError

        raise AdapterError(f"CACHE_MISS: missing {len(missing)} chapters", code="CACHE_MISS")

    # Also attach missing to exception? Caller will reconstruct missing list via checking again?
    # Instead we store missing in exception message; caller can parse.
    # Better to raise with missing attribute
    # We'll attach missing via exception's args and also raise with code

    # -------------------------------------------------------------------
    # Resolve selectors — start/end
    # -------------------------------------------------------------------
    if start_selector is None and end_selector is None:
        # try to resolve via core.clean.resolve_selectors via adapter
        try:
            clean_mod = importlib.import_module("core.clean")
            resolve_selectors = getattr(clean_mod, "resolve_selectors")
            # need adapter instance
            try:
                mod2 = importlib.import_module("adapters.novelphoenix")
                Adapter2 = getattr(mod2, "NovelPhoenixAdapter")
                adapter2 = Adapter2()
                selectors = resolve_selectors(adapter2)
                start_selector = selectors.start
                end_selector = selectors.end
            except Exception:
                # fallback default
                start_selector = "div#chapter-content"
                end_selector = None
        except Exception:
            start_selector = "div#chapter-content"
            end_selector = None
    if start_selector is not None and isinstance(start_selector, str):
        start_selector = start_selector.strip() or None
    if end_selector is not None and isinstance(end_selector, str):
        end_selector = end_selector.strip() or None
    if not start_selector:
        start_selector = "div#chapter-content"

    # -------------------------------------------------------------------
    # For each chapter: read_cache -> clean_html -> apply_filters_to_html
    # -------------------------------------------------------------------
    try:
        clean_mod3 = importlib.import_module("core.clean")
        clean_html = getattr(clean_mod3, "clean_html")
    except Exception as e:
        raise ImportError(f"clean module missing: {e}") from e

    try:
        filt_mod = importlib.import_module("core.filters")
        apply_filters_to_html = getattr(filt_mod, "apply_filters_to_html")
        # also apply_filters for text fallback
    except Exception as e:
        raise ImportError(f"filters module missing: {e}") from e

    chapter_data: List[Tuple[str, str, str]] = []  # (title, html, text)
    pending_images: List[Tuple[str, str, str, bytes]] = []  # (uid, file_name, media_type, data)
    for pos, url in enumerate(desired_urls):
        ch_num = from_i + pos
        logs.append(f"cleaning chapter {ch_num}")
        # set status cleaning? logs enough
        raw_html = read_cache(url, cache_dir) if cache_dir is not None else read_cache(url)
        if raw_html is None:
            # should have been caught earlier
            raise FileNotFoundError(f"cache miss chapter {ch_num}")
        # Extract title from raw html naive? Use soup h1/h2/h3 or fallback to url
        try:
            from bs4 import BeautifulSoup

            soup_tmp = BeautifulSoup(raw_html, "lxml")
            h = soup_tmp.find(["h1", "h2", "h3"])
            ch_title = h.get_text(strip=True) if h else f"Chapter {ch_num}"
            if not ch_title or not ch_title.strip():
                ch_title = f"Chapter {ch_num}"
            ch_title = ch_title.strip()[:200]
        except Exception:
            ch_title = f"Chapter {ch_num}"

        # clean
        try:
            cleaned_html, cleaned_text = clean_html(raw_html, start_selector, end_selector)
        except ValueError as ve:
            # invalid selector -> propagate as VALUE_ERROR
            raise ValueError(f"invalid selector: {ve}") from ve

        # filter once
        try:
            filtered_html, removed = apply_filters_to_html(cleaned_html, filters)
            logs.append(f"cleaned chapter {ch_num} removed {removed} lines")
        except Exception as e:
            # if filter invalid, treat as no filter
            filtered_html = cleaned_html
            logs.append(f"filter error chapter {ch_num}: {e}")

        # Derive filtered_text from filtered_html for EPUB? But we need html for EpubHtml
        # Ensure filtered_html is not empty; if empty, use cleaned_text wrapped in <p>
        if not filtered_html or not filtered_html.strip():
            # fallback to cleaned_text wrapped
            filtered_html = f"<p>{cleaned_text}</p>" if cleaned_text else "<p></p>"

        # Embed remote chapter images so the EPUB works offline (failures keep remote URL)
        try:
            filtered_html, img_items, embedded, skipped = embed_chapter_images(filtered_html, url, ch_num)
            if embedded:
                logs.append(f"images embedded {embedded} chapter {ch_num}")
                pending_images.extend(img_items)
            if skipped:
                logs.append(f"images skipped {skipped} chapter {ch_num}")
        except Exception as e:
            logs.append(f"image embed error chapter {ch_num}: {e}")

        # For EPUB XHTML, wrap in body? ebooklib expects HTML fragment
        # We'll keep filtered_html as fragment; epub.EpubHtml will wrap
        chapter_data.append((ch_title, filtered_html, cleaned_text))
        logs.append(f"done chapter {ch_num}")

    # -------------------------------------------------------------------
    # Assemble EpubBook
    # -------------------------------------------------------------------
    import ebooklib
    from ebooklib import epub as epub_lib

    book = epub_lib.EpubBook()
    # metadata
    book.set_identifier(f"{slug}-{from_i}-{to_i}-{hashlib.sha1(novel_url.encode()).hexdigest()[:8]}")
    book.set_title(title or slug)
    book.set_language("en")
    if author:
        book.add_author(author)
        # also add metadata creator
        try:
            book.add_metadata("DC", "creator", author)
        except Exception:
            pass

    # Cover best-effort
    cover_added = False
    cover_messages: List[str] = []
    if cover_url and not cover_url.lower().startswith("data:"):
        try:
            import requests

            resp = requests.get(cover_url, timeout=8, headers={"User-Agent": "SpeakEPUB/1.0"})
            if resp.status_code == 200 and resp.content:
                ctype = resp.headers.get("Content-Type", "").lower()
                # guess extension
                ext = "jpg"
                if "png" in ctype:
                    ext = "png"
                elif "jpeg" in ctype or "jpg" in ctype:
                    ext = "jpg"
                elif "webp" in ctype:
                    ext = "jpg"
                # try to detect from url
                if cover_url.lower().endswith(".png"):
                    ext = "png"
                elif cover_url.lower().endswith(".jpg") or cover_url.lower().endswith(".jpeg"):
                    ext = "jpg"
                cover_data = resp.content
                # data-url guard already
                if len(cover_data) > 0:
                    # use set_cover which creates cover image and html
                    try:
                        book.set_cover(f"cover.{ext}", cover_data)
                        cover_added = True
                        logs.append(f"cover added {cover_url}")
                    except Exception as ce:
                        # fallback manual
                        try:
                            img_item = epub_lib.EpubImage(
                                uid="cover-img",
                                file_name=f"images/cover.{ext}",
                                media_type=f"image/{ext}",
                                content=cover_data,
                            )
                            book.add_item(img_item)
                            cover_added = True
                            logs.append(f"cover added fallback {cover_url}")
                        except Exception as ce2:
                            cover_messages.append(f"cover embed failed: {ce2}")
                            logs.append(f"no cover (error) {ce2}")
                else:
                    cover_messages.append("cover empty")
                    logs.append("no cover (empty)")
            else:
                cover_messages.append(f"cover fetch {resp.status_code}")
                logs.append(f"no cover (status {resp.status_code})")
        except Exception as e:
            # offline-safe skip
            cover_messages.append(f"no cover (offline) {e}")
            logs.append(f"no cover (offline) {e}")
    elif cover_url and cover_url.lower().startswith("data:"):
        logs.append("no cover (data-url guard)")
        cover_messages.append("data-url cover skipped")
    else:
        logs.append("no cover")
        cover_messages.append("no cover")

    # Embedded chapter images collected during cleaning (offline reading)
    for uid, file_name, media_type, data in pending_images:
        try:
            img_item = epub_lib.EpubImage(uid=uid, file_name=file_name, media_type=media_type, content=data)
            book.add_item(img_item)
        except Exception as e:
            logs.append(f"image add failed {file_name}: {e}")

    # Create chapter EpubHtml items
    epub_chapters: List[Any] = []
    for idx, (ch_title, ch_html, _ch_text) in enumerate(chapter_data, start=1):
        file_name = f"chapter_{idx:03d}.xhtml"
        safe_title = ch_title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") if ch_title else f"Chapter {idx}"
        # ebooklib expects fragment, not full doc — it wraps itself
        # Use simple fragment: heading + filtered html fragment
        # filtered html already contains div#chapter-content wrapper; embed directly
        content = f"<h2>{safe_title}</h2>{ch_html}"
        chap = epub_lib.EpubHtml(title=ch_title, file_name=file_name, lang="en", content=content)
        chap.uid = f"chap_{idx}"
        book.add_item(chap)
        epub_chapters.append(chap)

    # TOC and spine
    # TOC is list of Links or Sections; for simplicity, list of chapters
    book.toc = tuple(epub_chapters)
    # Spine includes nav and each chapter
    book.spine = ["nav"] + epub_chapters
    # Add ncx and nav
    book.add_item(epub_lib.EpubNcx())
    book.add_item(epub_lib.EpubNav())

    # Add CSS maybe? Not needed

    # Write atomically
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    try:
        epub_lib.write_epub(str(tmp_path), book)
        tmp_path.replace(output_path)
        logs.append(f"epub written {output_path}")
    except Exception as e:
        # cleanup tmp
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass
        raise RuntimeError(f"epub write failed: {e}") from e

    # Run epubcheck
    ok, messages = run_epubcheck(output_path)
    # Combine cover messages if any?
    if cover_messages and not cover_added:
        messages.extend(cover_messages)
    # logs for epubcheck
    for m in messages:
        logs.append(f"epubcheck {m}")

    size = output_path.stat().st_size if output_path.exists() else 0

    # Determine epubcheck badge proxy flag: if messages contain proxy
    is_proxy = any("proxy" in m.lower() for m in messages)

    result: Dict[str, Any] = {
        "path": str(output_path),
        "size": size,
        "chapter_count": chapter_count,
        "epubcheck_ok": ok,
        "epubcheck_proxy": is_proxy,
        "messages": messages,
        "logs": logs,
        "is_proxy": is_proxy,
        # also return from/to for filename verification
        "from": from_i,
        "to": to_i,
        "slug": slug,
    }
    return result


__all__ = ["sanitize_filename", "run_epubcheck", "build_epub", "embed_chapter_images"]
