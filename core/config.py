"""
core/config.py — OS-aware venv path + store.json mirror + sidecar JSON-RPC handler.
AD-4, AD-10: Never bare `python`; single store.json via tauri-plugin-store.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict

# ---------------------------------------------------------------------------
# Venv resolution — OS-aware (AGENTS.md)
# ---------------------------------------------------------------------------

def get_venv_python() -> str:
    """
    Return OS-aware venv python path.
    Windows: venv/Scripts/python.exe
    POSIX  : venv/bin/python
    """
    # Resolve relative to project root (one level up from core/),
    # but we return the spec-expected relative string for Tauri shell spawn)
    if os.name == "nt":
        return "venv/Scripts/python.exe"
    return "venv/bin/python"


def get_venv_python_abs() -> Path:
    """Absolute path to venv python for local checks."""
    base = Path(__file__).resolve().parents[1]  # repo root
    rel = get_venv_python()
    return base / rel


# ---------------------------------------------------------------------------
# Store — single JSON mirroring CLI flags (AD-10)
# ---------------------------------------------------------------------------

DEFAULT_STORE: Dict[str, Any] = {
    "voice": "en-US-AndrewNeural",
    "rate": "+0%",
    "parallel": 3,
    "chunk-size": 3500,
    "retries": 5,
    "scrapeDelay": 4000,
    "safeMode": False,
    "keepEPUB": True,
    "keepMP3": True,
    "keepM4B": True,
    "outputDir": "",
    "filters": [],
    "autoBoilerplate": True,
    "audioBitrate": "32k",
    "selection": [],
    "selection_from": 1,
    "selection_to": 30,
    "selection_url": None,
    "updateAuto": True,
    "updateSkipped": "",
    "locale": "",
    "engine": "auto",
    "localVoice": "",
}

# Simple in-memory cache for listChapters url -> serialized list (FR2) — KEEP per re-review decision
# Politely caches last 20 url->list to avoid re-fetch same novel; no TTL, LRU evict oldest.
# Documented exception to Never:cache (Epics2-3) — lightweight chapter list cache is allowed for FR2.
_CHAPTER_CACHE: Dict[str, Any] = {}


def _normalize_cache_key(url: str) -> str:
    """Normalize url for _CHAPTER_CACHE — delegates to core.fetch (M1 single source)."""
    try:
        if not isinstance(url, str):
            return ""
        import importlib as _il_nck

        _fetch = _il_nck.import_module("core.fetch")
        fn = getattr(_fetch, "_normalize_cache_key", None)
        if callable(fn):
            return str(fn(url))
    except Exception:
        pass
    try:
        from urllib.parse import urlparse, urlunparse

        p = urlparse(url.strip())
        host = (p.hostname or "").lower().rstrip(".")
        if not host:
            return url.strip().lower().rstrip("/.")
        port = p.port
        scheme = p.scheme.lower()
        if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
            port = None
        netloc = host + (f":{port}" if port else "")
        path = p.path.rstrip("/").rstrip(".")
        normalized = urlunparse((scheme, netloc, path, "", "", ""))
        return normalized.rstrip("/.")
    except Exception:
        try:
            return url.strip().lower().rstrip("/.")
        except Exception:
            return ""


def _exc_code(exc: BaseException | None) -> str:
    """Best-effort machine code from exception chain (M1 — prefer attrs over message).

    Climbs __cause__/__context__, returns .code/.status-like attribute when
    present, else ''. Callers must not substring-match URLs/messages.
    """
    try:
        seen: set[int] = set()
        cur: BaseException | None = exc
        while cur is not None and id(cur) not in seen:
            seen.add(id(cur))
            for attr in ("code", "status", "status_code", "errno_name"):
                try:
                    v = getattr(cur, attr, None)
                except Exception:
                    v = None
                if isinstance(v, str) and v.strip():
                    return v.strip()
                if isinstance(v, int) and not isinstance(v, bool):
                    return str(v)
            resp = getattr(cur, "response", None)
            try:
                sc = getattr(resp, "status_code", None)
            except Exception:
                sc = None
            if isinstance(sc, int) and not isinstance(sc, bool):
                return str(sc)
            nxt = getattr(cur, "__cause__", None) or getattr(cur, "__context__", None)
            cur = nxt if isinstance(nxt, BaseException) else None
    except Exception:
        pass
    return ""


def _is_code(exc: BaseException | None, *codes: str) -> bool:
    """True when exception chain carries one of *codes (attr match) or message names it as a token."""
    try:
        c = _exc_code(exc).upper()
        if c and any(x.upper() in c for x in codes):
            return True
    except Exception:
        pass
    try:
        import re as _re_ic

        msg = str(exc) if exc is not None else ""
        return any(_re_ic.search(r"\b" + _re_ic.escape(x) + r"\b", msg) for x in codes)
    except Exception:
        return False


def get_store_path() -> Path:
    """
    Resolve store.json path.
    Tauri store defaults to app config dir; for CLI parity we also check
    ./store.json.
    """
    # Prefer Tauri app config dir if available via env (fallback to local)
    # For sidecar, use repo-root store.json
    for candidate in [
        Path("store.json"),
        Path.home() / ".config" / "speak-epub" / "store.json",
    ]:
        if candidate.is_file():
            return candidate
    # Default location for new store
    return Path("store.json")


def load_store() -> Dict[str, Any]:
    """Load store.json and merge with defaults (mirrors CLI flags)."""
    path = get_store_path()
    data: Dict[str, Any] = dict(DEFAULT_STORE)
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data.update(raw)
        except Exception:
            pass
    return data


def save_store(patch: Any) -> Dict[str, Any]:
    """Merge patch into store.json and persist atomically."""
    if not isinstance(patch, dict):
        raise TypeError("patch must be dict")
    path = get_store_path()
    current = load_store()
    current.update(patch)
    # validate JSON serializable before writing
    try:
        payload = json.dumps(current, indent=2, ensure_ascii=False)
    except TypeError as e:
        raise TypeError(f"patch not JSON serializable: {e}") from e
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(path)
    except OSError as e:
        raise OSError(f"store write failed {path}: {e}") from e
    return current


# ---------------------------------------------------------------------------
# JSON-RPC handler — stdin/stdout primary (AD-4 spike)
# ---------------------------------------------------------------------------

def handle_rpc(request: Any, emit_fn=None) -> Dict[str, Any]:
    """
    Handle a single JSON-RPC request dict {id, method, params}.
    Returns response dict {id, result} or {id, error}.
    Spike supports ping/hello; other methods return NotImplemented mock.

    Exception note (AD-1): core.config handles `search` / `listChapters` /
    `listChaptersCount` via dynamic importlib import of adapters inside handle_rpc.
    This preserves GUI->Core->Port->Adapter direction and avoids import-time cycles;
    static importlinter still sees core->core only. Documented exception for importlinter
    `core-no-adapters` — see .importlinter and pyproject.toml. Dynamic import is
    intentional to keep the contract while allowing the aggregator.

    emit_fn(event: str, payload: dict) — optional streaming hook for AD-6 bus
    (chapterStatus/partStatus/logLine/throttleChanged/done). Called synchronously
    inside fetch/TTS callbacks, also collected in logs/throttles/statuses for fallback.
    """
    if not isinstance(request, dict):
        return {"id": "0", "error": {"code": "BAD_REQUEST", "message": "request must be object"}}
    rid = request.get("id", "0")
    method = request.get("method")

    if method == "ping":
        return {"id": rid, "result": "pong"}
    if method == "hello":
        return {"id": rid, "result": {"echo": request.get("params"), "pong": True}}

    if method == "search":
        # Extract title from params
        params = request.get("params")
        title: Any = None
        if isinstance(params, dict):
            title = params.get("title", params.get("q", params.get("query")))
        elif isinstance(params, str):
            title = params
        else:
            title = params

        # Validation without network: empty/whitespace -> ValueError
        if not isinstance(title, str) or not title.strip():
            return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "title must be non-empty"}}
        title = title.strip()
        # Truncate len>300 ->200 before request (spec) — strip first
        if len(title) > 300:
            title = title[:200]

        # URL mode: if title looks like URL, delegate to guess + mock single row (no aggregator)
        if isinstance(title, str) and title.strip().lower().startswith(("http://", "https://")):
            # reuse listChaptersCount logic for URL
            return _handle_list_chapters_count(rid, title.strip())

        # Title mode -> aggregator parallel 5s via search_all + NovelPhoenixAdapter
        # Local import for aggregator (core->core, allowed). Adapter loaded via
        # importlib to keep static importlinter happy (documented exception).
        try:
            from .aggregator import search_all  # noqa: WPS433 local import allowed

            import importlib

            _mod = importlib.import_module("adapters.novelphoenix")
            NovelPhoenixAdapter = getattr(_mod, "NovelPhoenixAdapter")
        except Exception as e:
            return {"id": rid, "error": {"code": "IMPORT_FAILED", "message": str(e)}}

        try:
            adapters_list = [NovelPhoenixAdapter()]
            results = search_all(title, adapters_list)
            if not isinstance(results, list):
                results = []
            # No demo mocks here — empty stays empty. Tests stub search_all
            # directly; manual demo uses the network or recorded RPC fixtures.
        except Exception as e:
            # 4xx/5xx/timeout -> [] per spec, no crash — return empty result
            # but ValueError already handled above
            return {"id": rid, "result": []}

        # Serialize SearchResult -> JSON-friendly dict with site|title|chapters|link
        serialized: list[dict[str, Any]] = []
        for r in results:
            try:
                serialized.append(
                    {
                        "site": getattr(r, "site", ""),
                        "title": getattr(r, "title", ""),
                        "url": getattr(r, "url", ""),
                        "link": getattr(r, "url", ""),
                        "chapters": getattr(r, "chapter_count", None),
                        "chapter_count": getattr(r, "chapter_count", None),
                        "author": getattr(r, "author", None),
                        "cover_url": getattr(r, "cover_url", None),
                    }
                )
            except Exception:
                continue
        return {"id": rid, "result": serialized}

    if method == "listChapters":
        # Real listChapters — dynamic importlib to preserve GUI->Core->Port->Adapter (AD-1)
        params = request.get("params")
        url: Any = None
        if isinstance(params, dict):
            url = params.get("url", params.get("link", params.get("href")))
        elif isinstance(params, str):
            url = params
        else:
            url = params
        if isinstance(url, str):
            url = url.strip()
        if not isinstance(url, str) or not url:
            return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "url must be non-empty"}}
        import re
        from urllib.parse import urlparse

        if not re.match(r"^https?://", url, re.I):
            return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "url must be http(s)"}}
        try:
            parsed = urlparse(url)
            # use hostname (strips userinfo and port) + lower + strip trailing dot
            host = (parsed.hostname or "").lower().rstrip(".")
            if not host:
                return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "url must contain host"}}
            host_no_port = host  # already stripped
            # host guard — only novelphoenix allowed for real listChapters; others -> LIST_FAILED (jak search spec)
            allowed = host_no_port == "novelphoenix.com" or host_no_port == "www.novelphoenix.com" or host_no_port.endswith(".novelphoenix.com")
            if not allowed:
                return {"id": rid, "error": {"code": "LIST_FAILED", "message": f"unsupported host {host_no_port}"}}
        except Exception as e:
            return {"id": rid, "error": {"code": "VALUE_ERROR", "message": str(e)}}
        # Single-chapter shortcut: a pasted chapter URL (.../chapter-57 or
        # .../chapter/57) returns a one-row list instead of the whole novel
        # index. Title comes from a real fetchChapter (fast, single request).
        m_chapter = re.search(r"/chapter[-/](\d+)(?:[/?#].*)?$", url, re.I)
        if m_chapter:
            try:
                ch_num = int(m_chapter.group(1))
            except (TypeError, ValueError):
                ch_num = 0
            if ch_num < 1:
                return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "chapter number must be >= 1"}}
            try:
                import importlib as _il_ch

                _mod_ch = _il_ch.import_module("adapters.novelphoenix")
                ChapterAdapter = getattr(_mod_ch, "NovelPhoenixAdapter")
            except Exception as e:
                return {"id": rid, "error": {"code": "IMPORT_FAILED", "message": str(e)}}
            # cache hit before network (chapter URL has its own normalized key)
            ch_cache_key = _normalize_cache_key(url)
            if ch_cache_key in _CHAPTER_CACHE:
                cached_ch = _CHAPTER_CACHE[ch_cache_key]
                if isinstance(cached_ch, list):
                    return {"id": rid, "result": [dict(item) if isinstance(item, dict) else item for item in cached_ch]}
            try:
                chapter_adapter = ChapterAdapter()
                # Via fetch_one (not adapter.fetchChapter directly) so the raw
                # HTML lands in the fetch cache — otherwise a later buildEpub
                # for this chapter fails with CACHE_MISS (offline gate).
                _fetch_mod = _il_ch.import_module("core.fetch")
                fetch_one_fn = getattr(_fetch_mod, "fetch_one")
                cc = fetch_one_fn(url, chapter_adapter)
                if cc is None or not hasattr(cc, "html"):
                    return {"id": rid, "error": {"code": "LIST_FAILED", "message": "adapter returned non-list"}}
                ch_title = getattr(cc, "title", "") or ""
                if not isinstance(ch_title, str) or not ch_title.strip():
                    ch_title = f"Chapter {ch_num}"
                # page cover: prefer fetch_one result (works on cache hits too),
                # fallback to the adapter attr (fresh fetches capture og:image)
                ch_cover = None
                try:
                    ch_cover = getattr(cc, "cover_url", None)
                    if not isinstance(ch_cover, str) or not ch_cover.strip():
                        ch_cover = getattr(chapter_adapter, "_last_cover_url", None) or getattr(
                            chapter_adapter, "last_cover_url", None
                        )
                    if not isinstance(ch_cover, str) or not ch_cover.strip():
                        ch_cover = None
                except Exception:
                    ch_cover = None
                single = [{"index": ch_num, "title": ch_title.strip(), "url": url, "cover_url": ch_cover}]
                if len(_CHAPTER_CACHE) >= 20:
                    try:
                        _CHAPTER_CACHE.pop(next(iter(_CHAPTER_CACHE)))
                    except Exception:
                        pass
                _CHAPTER_CACHE[ch_cache_key] = [dict(item) for item in single]
                return {"id": rid, "result": [dict(item) for item in single]}
            except ValueError as e:
                return {"id": rid, "error": {"code": "VALUE_ERROR", "message": str(e)}}
            except Exception as e:
                code = getattr(e, "code", None)
                if code in ("LIST_FAILED", "FETCH_FAILED") or _is_code(e, "LIST_FAILED", "FETCH_FAILED"):
                    return {"id": rid, "error": {"code": "LIST_FAILED", "message": str(e)}}
                msg = str(e)
                if re.search(r"\b(4\d\d|5\d\d)\b", msg) or "timeout" in msg.lower() or "5xx" in msg.lower():
                    return {"id": rid, "error": {"code": "LIST_FAILED", "message": msg}}
                return {"id": rid, "error": {"code": "EXCEPTION", "message": msg}}
        # Dynamic import NovelPhoenixAdapter (importlinter exception documented in module docstring)
        try:
            import importlib

            _mod = importlib.import_module("adapters.novelphoenix")
            NovelPhoenixAdapter = getattr(_mod, "NovelPhoenixAdapter")
        except Exception as e:
            return {"id": rid, "error": {"code": "IMPORT_FAILED", "message": str(e)}}
        # cache hit before network — return deep copy to prevent poisoning (normalized key)
        cache_key = _normalize_cache_key(url)
        if cache_key in _CHAPTER_CACHE:
            cached = _CHAPTER_CACHE[cache_key]
            if isinstance(cached, list):
                return {"id": rid, "result": [dict(item) if isinstance(item, dict) else item for item in cached]}
        try:
            adapter = NovelPhoenixAdapter()
            lst = adapter.listChapters(url)
            if lst is None or not isinstance(lst, (list, tuple)):
                return {"id": rid, "error": {"code": "LIST_FAILED", "message": "adapter returned non-list"}}
            # Serialize ChapterInfo index/title/url + cover_url if available (hook expects cover)
            serialized: list[dict[str, Any]] = []
            cover_from_adapter: str | None = None
            try:
                # adapters/novelphoenix may expose last cover via _last_cover_url or similar
                cover_from_adapter = getattr(adapter, "_last_cover_url", None) or getattr(adapter, "last_cover_url", None)
            except Exception:
                pass
            seen_idx: set[int] = set()
            for enum_idx, ci in enumerate(lst, start=1):
                title = getattr(ci, "title", "") or "—"
                if not isinstance(title, str) or not title.strip():
                    title = "—"
                url_val = getattr(ci, "url", "") or ""
                cover_val = getattr(ci, "cover_url", None)
                # fallback for None or empty string "" (P4)
                if not cover_val:
                    cover_val = cover_from_adapter
                raw_idx = getattr(ci, "index", None)
                try:
                    idx_val = int(raw_idx) if raw_idx is not None else enum_idx
                    # guard NaN/float/0/negative -> fallback
                    if not isinstance(idx_val, int) or idx_val < 1:
                        idx_val = enum_idx
                except Exception:
                    idx_val = enum_idx
                # dedup duplicate indices (P5) — use enum_idx for second occurrence
                if idx_val in seen_idx:
                    idx_val = enum_idx
                    # ensure enum_idx not already taken (sparse case)
                    while idx_val in seen_idx:
                        idx_val += 1
                seen_idx.add(idx_val)
                serialized.append(
                    {
                        "index": idx_val,
                        "title": title,
                        "url": str(url_val),
                        "cover_url": cover_val,
                    }
                )
            # cache serialized result (cap 20 entries) — normalized key
            if len(_CHAPTER_CACHE) >= 20:
                # evict oldest (simple pop first)
                try:
                    _CHAPTER_CACHE.pop(next(iter(_CHAPTER_CACHE)))
                except Exception:
                    pass
            _CHAPTER_CACHE[cache_key] = [dict(item) for item in serialized]
            # also keep raw url key for direct hit? no — normalized only to deduplicate variants
            # return deep copy to prevent caller mutation poisoning cache
            return {"id": rid, "result": [dict(item) for item in serialized]}
        except ValueError as e:
            return {"id": rid, "error": {"code": "VALUE_ERROR", "message": str(e)}}
        except Exception as e:
            # Map AdapterError LIST_FAILED -> {"error":{"code":"LIST_FAILED",...}} not []
            code = getattr(e, "code", None)
            if code == "LIST_FAILED" or _is_code(e, "LIST_FAILED"):
                return {"id": rid, "error": {"code": "LIST_FAILED", "message": str(e)}}
            # Also handle requests HTTP errors as LIST_FAILED (403/429/5xx/timeout)
            msg = str(e)
            if re.search(r"\b(4\d\d|5\d\d)\b", msg) or "timeout" in msg.lower() or "5xx" in msg.lower():
                return {"id": rid, "error": {"code": "LIST_FAILED", "message": msg}}
            return {"id": rid, "error": {"code": "EXCEPTION", "message": msg}}

    if method in ("fetchChapter", "fetchChapters", "getCacheStatus"):
        # AD-1: dynamic import preserves GUI->Core->Port->Adapter, reuse _normalize_cache_key & cache_key from core.fetch
        import re as _re2
        from urllib.parse import urlparse as _urlparse2

        def _validate_url(u: str, allow_missing_host=False):
            if not isinstance(u, str) or not u.strip():
                return None, "VALUE_ERROR", "url must be non-empty"
            u = u.strip()
            if not _re2.match(r"^https?://", u, _re2.I):
                return None, "VALUE_ERROR", "url must be http(s)"
            try:
                parsed = _urlparse2(u)
                host = (parsed.hostname or "").lower().rstrip(".")
                if not host:
                    return None, "VALUE_ERROR", "url must contain host"
                allowed = host == "novelphoenix.com" or host == "www.novelphoenix.com" or host.endswith(".novelphoenix.com")
                if not allowed:
                    return None, "LIST_FAILED", f"unsupported host {host}"
                return u, None, None
            except Exception as e:
                return None, "VALUE_ERROR", str(e)

        # Dynamic import adapter
        try:
            import importlib as _il
            _mod = _il.import_module("adapters.novelphoenix")
            NovelPhoenixAdapter = getattr(_mod, "NovelPhoenixAdapter")
        except Exception as e:
            return {"id": rid, "error": {"code": "IMPORT_FAILED", "message": str(e)}}

        # Handle single fetchChapter
        if method == "fetchChapter":
            params = request.get("params")
            url: Any = None
            if isinstance(params, dict):
                url = params.get("url", params.get("link", params.get("href")))
            elif isinstance(params, str):
                url = params
            else:
                url = params
            if isinstance(url, str):
                url = url.strip()
            validated, err_code, err_msg = _validate_url(url if isinstance(url, str) else "", False)  # type: ignore
            if err_code:
                return {"id": rid, "error": {"code": err_code, "message": err_msg}}
            url = validated  # type: ignore
            # dynamic import core.fetch fetch_one
            try:
                import importlib as _il2
                _fmod = _il2.import_module("core.fetch")
                fetch_one_fn = getattr(_fmod, "fetch_one")
            except Exception as e:
                return {"id": rid, "error": {"code": "IMPORT_FAILED", "message": str(e)}}
            try:
                adapter = NovelPhoenixAdapter()
                cc = fetch_one_fn(url, adapter)
                if cc is None or not hasattr(cc, "html"):
                    return {"id": rid, "error": {"code": "LIST_FAILED", "message": "adapter returned non-list"}}
                cover = None
                for _attr in ("_last_cover_url", "last_cover_url"):
                    try:
                        v = getattr(adapter, _attr, None)
                        if isinstance(v, str) and v.strip():
                            cover = v
                            break
                    except Exception:
                        continue
                # cover fallback: also try cc.cover_url if exists
                try:
                    cc_cover = getattr(cc, "cover_url", None)
                    if isinstance(cc_cover, str) and cc_cover.strip():
                        cover = cc_cover
                except Exception:
                    pass
                serialized = {
                    "url": getattr(cc, "url", url),
                    "title": getattr(cc, "title", ""),
                    "html": getattr(cc, "html", ""),
                    "text": getattr(cc, "text", ""),
                    "cover_url": cover,
                }
                return {"id": rid, "result": serialized}
            except ValueError as e:
                return {"id": rid, "error": {"code": "VALUE_ERROR", "message": str(e)}}
            except Exception as e:
                code = getattr(e, "code", None)
                if code == "LIST_FAILED" or _is_code(e, "LIST_FAILED", "FETCH_FAILED"):
                    return {"id": rid, "error": {"code": "LIST_FAILED", "message": str(e)}}
                msg = str(e)
                if _re2.search(r"\b(4\d\d|5\d\d)\b", msg) or "timeout" in msg.lower() or "5xx" in msg.lower():
                    return {"id": rid, "error": {"code": "LIST_FAILED", "message": msg}}
                return {"id": rid, "error": {"code": "EXCEPTION", "message": msg}}

        # Handle fetchChapters batch and getCacheStatus
        # Extract params
        params = request.get("params")
        urls: Any = None
        novelUrl: Any = None
        from_val: Any = None
        to_val: Any = None
        if isinstance(params, list):
            urls = params
        elif isinstance(params, dict):
            # urls variants
            urls = params.get("urls", params.get("url", params.get("links", params.get("chapters"))))
            # if urls is single string and novelUrl also maybe string, ensure distinction
            novelUrl = params.get("novelUrl", params.get("novel_url", params.get("novelURL", params.get("novel"))))
            # also try "novelUrl" case-insensitive fallback? already
            from_val = params.get("from", params.get("selection_from", params.get("from_idx", params.get("fromIdx"))))
            to_val = params.get("to", params.get("selection_to", params.get("to_idx", params.get("toIdx", params.get("end")))))
            # handle case where urls is None and params has single url key that is novelUrl and not chapters
            if isinstance(urls, str):
                urls = [urls]
            # if urls came from params.get("url") and that url is actually novelUrl (same), and novelUrl not set, need to decide
            if novelUrl is None and isinstance(params.get("url"), str) and urls is None:
                # ambiguous, treat as novelUrl if not list
                pass
            if isinstance(urls, dict):
                urls = [urls]
            # also handle params like {"urls": [], "novelUrl": "...", "from": 20, "to": 100}
            if urls is None:
                urls = []
            if not isinstance(urls, (list, tuple)):
                urls = [urls] if urls else []
            # normalize urls list
            cleaned: list[str] = []
            for u in urls:  # type: ignore
                if isinstance(u, str) and u.strip():
                    cleaned.append(u.strip())
                elif isinstance(u, dict):
                    # dict with url key
                    uu = u.get("url") or u.get("link") or u.get("href")
                    if isinstance(uu, str) and uu.strip():
                        cleaned.append(uu.strip())
            urls = cleaned
            # if novelUrl is list incorrectly, fix
            if isinstance(novelUrl, list):
                novelUrl = None
            if isinstance(novelUrl, str):
                novelUrl = novelUrl.strip() or None
        elif isinstance(params, str):
            urls = [params]
        else:
            urls = []

        if urls is None:
            urls = []
        # Validate urls if present + guard payload size + dedup
        if isinstance(urls, (list, tuple)) and len(urls) > 0:  # type: ignore
            if len(urls) > 1000:
                return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "too many urls (max 1000)"}}
            # dedup preserve order before validation
            try:
                urls = list(dict.fromkeys(urls))  # type: ignore
            except Exception:
                pass
            for u in urls:  # type: ignore
                _, err_code2, err_msg2 = _validate_url(u, False)  # type: ignore
                if err_code2:
                    return {"id": rid, "error": {"code": err_code2, "message": err_msg2}}
        # Validate novelUrl if present
        if isinstance(novelUrl, str) and novelUrl.strip():
            _, err_code3, err_msg3 = _validate_url(novelUrl, False)
            if err_code3:
                return {"id": rid, "error": {"code": err_code3, "message": err_msg3}}
            novelUrl = novelUrl.strip()  # type: ignore
        else:
            novelUrl = novelUrl if isinstance(novelUrl, str) else None
            if isinstance(novelUrl, str) and not novelUrl.strip():
                novelUrl = None

        # ensure tuple -> list for downstream fetch_many
        if isinstance(urls, tuple):
            urls = list(urls)  # type: ignore
        if not urls and not novelUrl:
            return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "urls or novelUrl required"}}

        # getCacheStatus variant — return diff without fetching
        if method == "getCacheStatus":
            try:
                import importlib as _il3
                _fmod3 = _il3.import_module("core.fetch")
                get_cache_path_fn = getattr(_fmod3, "get_cache_path")
                # Build desired list
                desired: list[str] = []
                if urls:
                    desired = list(urls)  # type: ignore
                elif novelUrl:
                    adapter_tmp = NovelPhoenixAdapter()
                    fresh = adapter_tmp.listChapters(novelUrl)  # type: ignore
                    if fresh is None or not isinstance(fresh, (list, tuple)):
                        return {"id": rid, "error": {"code": "LIST_FAILED", "message": "adapter returned non-list"}}
                    for ci in fresh:  # type: ignore
                        uu = getattr(ci, "url", None)
                        if isinstance(uu, str) and uu.strip():
                            desired.append(uu.strip())
                    # slice by from/to if provided
                    if from_val is not None or to_val is not None:
                        # need to map from/to indices to urls
                        from_i = None
                        to_i = None
                        try:
                            from_i = int(from_val) if from_val is not None else None  # type: ignore
                        except Exception:
                            from_i = None
                        try:
                            to_i = int(to_val) if to_val is not None else None  # type: ignore
                        except Exception:
                            to_i = None
                        if from_i is not None or to_i is not None:
                            # assume fresh sorted by index
                            try:
                                fresh_sorted = sorted(fresh, key=lambda ci: getattr(ci, "index", 0))  # type: ignore
                            except Exception:
                                fresh_sorted = list(fresh)  # type: ignore
                            N = len(fresh_sorted)
                            f = max(1, min(from_i, N)) if from_i is not None else 1
                            t = max(1, min(to_i, N)) if to_i is not None else N
                            if f > t:
                                f, t = t, f
                            desired = []
                            for ci in fresh_sorted:  # type: ignore
                                idx = getattr(ci, "index", None)
                                if idx is not None:
                                    try:
                                        ii = int(idx)
                                        if f <= ii <= t:
                                            uu2 = getattr(ci, "url", "")
                                            if isinstance(uu2, str) and uu2.strip():
                                                desired.append(uu2.strip())
                                    except Exception:
                                        continue
                            if not desired:
                                # fallback slice
                                desired = [getattr(ci, "url", "").strip() for ci in fresh_sorted[f - 1 : t] if getattr(ci, "url", "")]  # type: ignore
                skipped = sum(1 for u in desired if get_cache_path_fn(u).is_file())
                total = len(desired)
                missing = total - skipped
                badge = f"pominięto {skipped}" if skipped else None
                if missing and skipped:
                    badge = f"pominięto {skipped}, pobieram {skipped+1}–{skipped+missing}"
                return {"id": rid, "result": {"total": total, "skipped": skipped, "missing": missing, "badge": badge, "desired": desired}}
            except ValueError as e:
                return {"id": rid, "error": {"code": "VALUE_ERROR", "message": str(e)}}
            except Exception as e:
                code = getattr(e, "code", None)
                if code == "LIST_FAILED" or _is_code(e, "LIST_FAILED"):
                    return {"id": rid, "error": {"code": "LIST_FAILED", "message": str(e)}}
                return {"id": rid, "error": {"code": "EXCEPTION", "message": str(e)}}

        # Normal fetchChapters via core.fetch.fetch_many
        try:
            import importlib as _il4
            _fmod4 = _il4.import_module("core.fetch")
            fetch_many_fn = getattr(_fmod4, "fetch_many")
        except Exception as e:
            return {"id": rid, "error": {"code": "IMPORT_FAILED", "message": str(e)}}

        def _to_int(v):
            if v is None or v == "":
                return None
            try:
                iv = int(v)  # type: ignore
                if iv < 1:
                    return 1
                return max(1, min(iv, 100000))
            except Exception:
                return None

        from_idx_i = _to_int(from_val)
        to_idx_i = _to_int(to_val)

        try:
            adapter = NovelPhoenixAdapter()
            logs: list[str] = []
            statuses: dict[int, str] = {}
            throttles: list[dict[str, Any]] = []

            def on_log(line: str):
                logs.append(line)
                if emit_fn:
                    try:
                        emit_fn("logLine", {"line": line})
                    except Exception:
                        pass

            def on_status(idx: int, status: str):
                statuses[idx] = status
                if emit_fn:
                    try:
                        emit_fn("chapterStatus", {"chapter": int(idx), "status": status})
                    except Exception:
                        pass

            def on_throttle(tier: str, delay: int):
                throttles.append({"tier": tier, "delay": delay})
                if emit_fn:
                    try:
                        emit_fn("throttleChanged", {"tier": tier, "delay": delay})
                    except Exception:
                        pass

            # Ensure urls is list
            urls_list = list(urls) if isinstance(urls, (list, tuple)) else []
            result = fetch_many_fn(
                urls_list,
                adapter,
                novel_url=novelUrl,
                from_idx=from_idx_i,
                to_idx=to_idx_i,
                on_status=on_status,
                on_log=on_log,
                on_throttle=on_throttle,
            )
            if result.get("error") == "LOCKED":
                return {"id": rid, "error": {"code": "LOCKED", "message": "fetch already in progress, queue locked"}}
            # Check for non-list fresh error inside fetch_many (it raises AdapterError)
            fetched = result.get("fetched", []) or result.get("results", []) or []
            serialized_chapters: list[dict[str, Any]] = []
            for cc in fetched:  # type: ignore
                try:
                    cover = None
                    for _attr2 in ("_last_cover_url", "last_cover_url"):
                        try:
                            v2 = getattr(adapter, _attr2, None)
                            if isinstance(v2, str) and v2.strip():
                                cover = v2
                                break
                        except Exception:
                            continue
                    try:
                        cc_cover = getattr(cc, "cover_url", None)
                        if isinstance(cc_cover, str) and cc_cover.strip():
                            cover = cc_cover
                    except Exception:
                        pass
                    serialized_chapters.append(
                        {
                            "url": getattr(cc, "url", ""),
                            "title": getattr(cc, "title", ""),
                            "html": getattr(cc, "html", ""),
                            "text": getattr(cc, "text", ""),
                            "cover_url": cover,
                        }
                    )
                except Exception:
                    continue
            response_result = {
                "chapters": serialized_chapters,
                "skipped": result.get("skipped", 0),
                "total": result.get("total", len(urls_list)),
                "badge": result.get("badge"),
                "logs": logs,
                "throttles": throttles,
                "missing": result.get("missing", []),
                "failed": result.get("failed", []),
                "desired": result.get("desired", urls_list),
            }
            return {"id": rid, "result": response_result}
        except ValueError as e:
            return {"id": rid, "error": {"code": "VALUE_ERROR", "message": str(e)}}
        except Exception as e:
            code = getattr(e, "code", None)
            if code == "LIST_FAILED" or _is_code(e, "LIST_FAILED", "FETCH_FAILED"):
                return {"id": rid, "error": {"code": "LIST_FAILED", "message": str(e)}}
            msg = str(e)
            if _re2.search(r"\b(4\d\d|5\d\d)\b", msg) or "timeout" in msg.lower() or "5xx" in msg.lower():
                return {"id": rid, "error": {"code": "LIST_FAILED", "message": msg}}
            return {"id": rid, "error": {"code": "EXCEPTION", "message": msg}}

    # TTS live — run_part_jobs with event bus (Story 4.1)
    if method in ("runTtsJobs", "run_part_jobs", "runPartJobs"):
        import asyncio as _async
        import importlib as _il_tts
        params = request.get("params") or {}
        if not isinstance(params, dict):
            return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "params must be object"}}
        # Support jobs as list of PartJob dicts or synthetic chapter spec
        jobs_param = params.get("jobs", params.get("partJobs", params.get("part_jobs")))
        voice = params.get("voice", params.get("voiceName", "en-US-AndrewNeural"))
        parallel = params.get("parallel", 3)
        retries = params.get("retries", 5)
        # Parse voice/parallel/retries
        try:
            parallel = int(parallel)
            if parallel < 1:
                parallel = 1
            if parallel > 6:
                parallel = 6
        except Exception:
            parallel = 3
        try:
            retries = int(retries)
            if retries < 1:
                retries = 5
        except Exception:
            retries = 5
        if isinstance(voice, str):
            voice = voice.strip() or "en-US-AndrewNeural"
        else:
            voice = "en-US-AndrewNeural"
        # Build jobs list
        jobs: list = []
        if isinstance(jobs_param, list) and jobs_param:
            # Check if first element is dict with PartJob fields
            try:
                _tmod = _il_tts.import_module("core.tts")
                PartJobCls = getattr(_tmod, "PartJob")
                for j in jobs_param:  # type: ignore
                    if isinstance(j, dict):
                        # Support both snake and camel
                        cn = j.get("chapter_number", j.get("chapterNumber", j.get("chapter")))
                        pn = j.get("part_number", j.get("partNumber", j.get("part")))
                        pc = j.get("part_count", j.get("partCount", j.get("count")))
                        txt = j.get("text", "")
                        outp = j.get("output_path", j.get("outputPath", j.get("path")))
                        is_final = j.get("is_final_chapter_file", j.get("isFinal", j.get("is_final", False)))
                        if cn is None or pn is None or outp is None:
                            continue
                        try:
                            # guard part_count: must be >=1
                            try:
                                pc_val = int(pc) if pc is not None else 1
                                if pc_val <= 0:
                                    pc_val = 1
                            except Exception:
                                pc_val = 1
                            # robust is_final handling: string "false"/"0" -> False
                            if isinstance(is_final, str):
                                is_final_bool = is_final.strip().lower() in ("1", "true", "yes")
                            else:
                                is_final_bool = bool(is_final)
                            jobs.append(
                                PartJobCls(
                                    chapter_number=int(cn),
                                    chapter_title=str(j.get("chapter_title", j.get("chapterTitle", f"Chapter {cn}"))),
                                    part_number=int(pn),
                                    part_count=pc_val,
                                    text=str(txt),
                                    output_path=str(outp),
                                    is_final_chapter_file=is_final_bool,
                                )
                            )
                        except Exception:
                            continue
                    else:
                        # Already PartJob instance?
                        jobs.append(j)
            except Exception as e:
                return {"id": rid, "error": {"code": "EXCEPTION", "message": str(e)}}
        elif isinstance(params.get("chapters"), list):
            # Alternative: build plan from chapters + outputDir
            try:
                chaps = params.get("chapters")  # list of [index, title, text]
                output_dir = params.get("outputDir", params.get("output_dir", "output"))
                chunk_size = params.get("chunkSize", params.get("chunk_size", 3500))
                try:
                    chunk_size = int(chunk_size)
                    chunk_size = max(500, min(5000, chunk_size))
                except Exception:
                    chunk_size = 3500
                _tmod2 = _il_tts.import_module("core.tts")
                build_plan_fn = getattr(_tmod2, "build_generation_plan")
                # Normalize chapters to tuple
                norm_chaps = []
                for c in chaps:  # type: ignore
                    if isinstance(c, (list, tuple)) and len(c) >= 3:
                        norm_chaps.append((int(c[0]), str(c[1]), str(c[2])))
                    elif isinstance(c, dict):
                        norm_chaps.append((int(c.get("index", 0)), str(c.get("title", "")), str(c.get("text", ""))))
                _, jobs = build_plan_fn(norm_chaps, str(output_dir), chunk_size)
            except Exception as e:
                return {"id": rid, "error": {"code": "EXCEPTION", "message": str(e)}}
        # If still empty jobs, return empty result (resume case)
        try:
            _tmod3 = _il_tts.import_module("core.tts")
            run_jobs_fn = getattr(_tmod3, "run_part_jobs")
            tts_logs: list[str] = []
            part_throttles: list = []

            def tts_on_log(line: str):
                tts_logs.append(line)
                if len(tts_logs) > 1000:
                    tts_logs.pop(0)
                if emit_fn:
                    try:
                        emit_fn("logLine", {"line": line})
                    except Exception:
                        pass

            def tts_on_part(payload: dict):
                if emit_fn:
                    try:
                        emit_fn("partStatus", payload)
                    except Exception:
                        pass
                # also log skip for badge? handle skip -> logLine already via on_log

            def tts_on_progress(done: int, total: int):
                if emit_fn:
                    try:
                        emit_fn("logLine", {"line": f"progress: {done}/{total} TTS part job(s) complete"})
                    except Exception:
                        pass

            # Run async jobs
            try:
                loop = _async.get_event_loop()
                if loop.is_closed():
                    raise RuntimeError("closed loop")
            except Exception:
                loop = _async.new_event_loop()
                _async.set_event_loop(loop)
            try:
                if loop.is_running():
                    # Already in async context? Create task via asyncio.run replacement
                    # Use new loop in thread to avoid deadlock
                    import concurrent.futures as _cf
                    import threading as _th

                    result_box: dict = {}
                    exc_box: dict = {}

                    def _run_in_new_loop():
                        new_loop = _async.new_event_loop()
                        _async.set_event_loop(new_loop)
                        try:
                            new_loop.run_until_complete(run_jobs_fn(jobs, voice, parallel, retries, on_part_status=tts_on_part, on_log=tts_on_log, on_progress=tts_on_progress))
                            result_box["ok"] = True
                        except Exception as e:
                            exc_box["e"] = e
                        finally:
                            new_loop.close()

                    th = _th.Thread(target=_run_in_new_loop, daemon=True)
                    th.start()
                    th.join(timeout=300)
                    if th.is_alive():
                        raise TimeoutError("TTS timed out after 300s; partial files kept, re-run to resume")
                    if "e" in exc_box:
                        raise exc_box["e"]
                else:
                    loop.run_until_complete(run_jobs_fn(jobs, voice, parallel, retries, on_part_status=tts_on_part, on_log=tts_on_log, on_progress=tts_on_progress))
            except RuntimeError as re:
                # fallback to asyncio.run if loop handling failed
                if "already running" in str(re).lower() or "closed" in str(re).lower():
                    _async.run(run_jobs_fn(jobs, voice, parallel, retries, on_part_status=tts_on_part, on_log=tts_on_log, on_progress=tts_on_progress))
                else:
                    raise
            if emit_fn:
                try:
                    emit_fn("done", {"result": "ok"})
                except Exception:
                    pass
            return {"id": rid, "result": {"done": True, "logs": tts_logs, "jobs": len(jobs)}}
        except Exception as e:
            msg = str(e)
            if emit_fn:
                try:
                    emit_fn("logLine", {"line": f"error {msg}"})
                    emit_fn("done", {"error": msg})
                except Exception:
                    pass
            return {"id": rid, "error": {"code": "EXCEPTION", "message": msg}}

    # Selection persistence — Core owns selection (D2/D3 patch)
    if method == "getSelection":
        try:
            data = load_store()
            sel = data.get("selection", [])
            if not isinstance(sel, list):
                sel = []
            # sanitize to ints 1..N if possible
            sanitized: list[int] = []
            for v in sel:
                try:
                    iv = int(v)
                    if iv >= 1:
                        sanitized.append(iv)
                except Exception:
                    continue
            # sanitize from/to — clamp 1..100000, fallback defaults on corruption
            def _safe_from_to(val, default):
                try:
                    iv = int(val)
                    # treat NaN/bool already via int, but reject <1
                    if iv < 1:
                        return 1
                    return max(1, min(iv, 100000))
                except Exception:
                    return default

            safe_from = _safe_from_to(data.get("selection_from", 1), 1)
            safe_to = _safe_from_to(data.get("selection_to", 30), 30)
            # swap if inverted even on read (handles stale stored invert)
            if safe_from > safe_to:
                safe_from, safe_to = safe_to, safe_from
            return {
                "id": rid,
                "result": {
                    "selection": sanitized,
                    "from": safe_from,
                    "to": safe_to,
                    "url": data.get("selection_url"),
                },
            }
        except Exception as e:
            return {"id": rid, "error": {"code": "EXCEPTION", "message": str(e)}}

    if method == "setSelection":
        try:
            params = request.get("params") or {}
            if not isinstance(params, dict):
                params = {"selection": params}
            sel = params.get("selection", params.get("selected", []))
            frm = params.get("from", params.get("selection_from"))
            to = params.get("to", params.get("selection_to"))
            url_sel = params.get("url", params.get("selection_url"))
            if sel is None:
                sel = []
            if not isinstance(sel, list):
                sel = [sel]
            sanitized: list[int] = []
            for v in sel:
                try:
                    iv = int(v)
                    if iv >= 1:
                        sanitized.append(iv)
                except Exception:
                    continue
            # dedup + sort + cap
            sanitized = sorted(set(sanitized))
            patch: Dict[str, Any] = {"selection": sanitized}
            if frm is not None:
                try:
                    fv = int(frm)
                    fv = max(1, min(fv, 100000))
                    patch["selection_from"] = fv
                except Exception:
                    pass
            if to is not None:
                try:
                    tv = int(to)
                    tv = max(1, min(tv, 100000))
                    patch["selection_to"] = tv
                except Exception:
                    pass
            # swap even when only one field provided — compare effective values (P3)
            # load current effective from/to for comparison
            try:
                _cur = load_store()
                cur_from = _cur.get("selection_from", 1)
                cur_to = _cur.get("selection_to", 30)
                eff_from = patch.get("selection_from", cur_from)
                eff_to = patch.get("selection_to", cur_to)
                # sanitize effective for comparison (int + clamp already)
                try:
                    eff_from = max(1, min(int(eff_from), 100000))
                except Exception:
                    eff_from = cur_from
                try:
                    eff_to = max(1, min(int(eff_to), 100000))
                except Exception:
                    eff_to = cur_to
                if eff_from > eff_to:
                    # fix collapse: when only one field in patch, set both to maintain swapped range
                    if "selection_from" in patch and "selection_to" in patch:
                        patch["selection_from"], patch["selection_to"] = eff_to, eff_from
                    elif "selection_from" in patch:
                        patch["selection_from"] = eff_to
                        patch["selection_to"] = eff_from
                    elif "selection_to" in patch:
                        patch["selection_to"] = eff_from
                        patch["selection_from"] = eff_to
            except Exception:
                pass
            if isinstance(url_sel, str) and url_sel.strip():
                if url_sel.strip().lower().startswith(("http://", "https://")):
                    patch["selection_url"] = url_sel.strip()[:500]
            elif url_sel is None:
                # explicit clear (P19) — allow null to wipe stale url
                patch["selection_url"] = None
            elif isinstance(url_sel, str) and not url_sel.strip():
                # empty string also clears? treat as clear
                patch["selection_url"] = None
            save_store(patch)
            return {"id": rid, "result": {"saved": True, "selection": sanitized}}
        except Exception as e:
            return {"id": rid, "error": {"code": "EXCEPTION", "message": str(e)}}

    if method in ("listChaptersCount", "guessAndCount", "guessAdapter"):
        params = request.get("params")
        url: Any = None
        if isinstance(params, dict):
            url = params.get("url", params.get("link", params.get("href")))
        elif isinstance(params, str):
            url = params
        else:
            url = params
        if isinstance(url, str):
            url = url.strip()
        if not isinstance(url, str) or not url:
            return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "url must be non-empty"}}
        # For guessAdapter, just return guess
        if method == "guessAdapter":
            try:
                import importlib

                _mod = importlib.import_module("adapters.base")
                guess_adapter = getattr(_mod, "guess_adapter")
                g = guess_adapter(url)
                return {"id": rid, "result": {"guess": g, "url": url}}
            except Exception as e:
                return {"id": rid, "error": {"code": "EXCEPTION", "message": str(e)}}
        return _handle_list_chapters_count(rid, url)

    # Preview & selector boundary — AD-7 (Story 2.2)
    if method in ("getSelectors", "previewChapter", "saveSelectors", "clearSelectors"):
        import re as _re3
        from urllib.parse import urlparse as _urlparse3

        def _site_from_url(u: str) -> str | None:
            try:
                p = _urlparse3(u.strip())
                host = (p.hostname or "").lower().rstrip(".")
                if host and host.startswith("www."):
                    host = host[4:]
                return host or None
            except Exception:
                return None

        # Dynamic import adapter + clean
        try:
            import importlib as _il5

            _mod5 = _il5.import_module("adapters.novelphoenix")
            NovelPhoenixAdapter5 = getattr(_mod5, "NovelPhoenixAdapter")
            _cmod = _il5.import_module("core.clean")
            resolve_selectors_fn = getattr(_cmod, "resolve_selectors")
            clean_html_fn = getattr(_cmod, "clean_html")
            load_overrides_fn = getattr(_cmod, "load_overrides")
            save_overrides_fn = getattr(_cmod, "save_overrides")
            clear_overrides_fn = getattr(_cmod, "clear_overrides")
        except Exception as e:
            return {"id": rid, "error": {"code": "IMPORT_FAILED", "message": str(e)}}

        params = request.get("params")
        url_param: Any = None
        site_param: Any = None
        start_param: Any = None
        end_param: Any = None
        if isinstance(params, dict):
            url_param = params.get("url", params.get("link", params.get("href")))
            site_param = params.get("site", params.get("hostname", params.get("host")))
            start_param = params.get("start", params.get("startSelector", params.get("selectorStart")))
            end_param = params.get("end", params.get("endSelector", params.get("selectorEnd")))
            # also handle start/end inside selectors dict
            sel_dict = params.get("selectors")
            if isinstance(sel_dict, dict):
                start_param = sel_dict.get("start", start_param)
                end_param = sel_dict.get("end", end_param)
        elif isinstance(params, str):
            url_param = params

        # helper to resolve site — normalize www. strip for canonical overrides/<site>.json
        # H7: strict hostname validation — rejects slash/dotdot/traversal payloads.
        # NOTE: no `re.` here (see H8 note — `re` is function-local in handle_rpc).
        def _resolve_site() -> str | None:
            if isinstance(url_param, str) and url_param.strip():
                s = _site_from_url(url_param.strip())
                if s:
                    return s
            if isinstance(site_param, str) and site_param.strip():
                host = site_param.strip().lower().rstrip(".")
                if host.startswith("www."):
                    host = host[4:]
                if not host or len(host) > 253 or ".." in host or "/" in host or "\\" in host:
                    return None
                labels = host.split(".")
                if not all(
                    len(lb) >= 1 and len(lb) <= 63
                    and lb[0].isalnum() and lb[-1].isalnum()
                    and all(ch.isalnum() or ch == "-" for ch in lb)
                    for lb in labels
                ):
                    return None
                return host
            return None

        if method == "getSelectors":
            site = _resolve_site()
            if not site:
                # R3: explicit but unresolvable site/url must error — silently
                # falling back to novelphoenix would read/save/clear the wrong
                # site's overrides (data loss).
                if (isinstance(site_param, str) and site_param.strip()) or (
                    isinstance(url_param, str) and url_param.strip()
                ):
                    return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "invalid site or url"}}
                # fallback to novelphoenix default
                site = "novelphoenix.com"
            # validate host if url provided
            if isinstance(url_param, str) and url_param.strip():
                if not _re3.match(r"^https?://", url_param.strip(), _re3.I):
                    return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "url must be http(s)"}}
                try:
                    p = _urlparse3(url_param.strip())
                    host = (p.hostname or "").lower().rstrip(".")
                    if not host:
                        return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "url must contain host"}}
                    allowed = host == "novelphoenix.com" or host == "www.novelphoenix.com" or host.endswith(".novelphoenix.com")
                    if not allowed:
                        return {"id": rid, "error": {"code": "LIST_FAILED", "message": f"unsupported host {host}"}}
                except Exception as e:
                    return {"id": rid, "error": {"code": "VALUE_ERROR", "message": str(e)}}
            try:
                adapter = NovelPhoenixAdapter5()
                default_sel = adapter.getSelectors()
                site_key = site
                ov = load_overrides_fn(site_key)
                # resolve effective
                eff = resolve_selectors_fn(adapter)  # uses override if exists
                return {"id": rid, "result": {
                    "site": site_key,
                    "start": eff.start,
                    "end": eff.end,
                    "defaultStart": getattr(default_sel, "start", None),
                    "defaultEnd": getattr(default_sel, "end", None),
                    "override": {"start": ov.start, "end": ov.end} if ov else None,
                }}
            except Exception as e:
                return {"id": rid, "error": {"code": "EXCEPTION", "message": str(e)}}

        if method == "previewChapter":
            # requires url
            if not isinstance(url_param, str) or not url_param.strip():
                return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "url must be non-empty"}}
            url_param = url_param.strip()
            if not _re3.match(r"^https?://", url_param, _re3.I):
                return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "url must be http(s)"}}
            try:
                p = _urlparse3(url_param)
                host = (p.hostname or "").lower().rstrip(".")
                if not host:
                    return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "url must contain host"}}
                allowed = host == "novelphoenix.com" or host == "www.novelphoenix.com" or host.endswith(".novelphoenix.com")
                if not allowed:
                    return {"id": rid, "error": {"code": "LIST_FAILED", "message": f"unsupported host {host}"}}
            except Exception as e:
                return {"id": rid, "error": {"code": "VALUE_ERROR", "message": str(e)}}
            # normalize start/end (None if empty string)
            start_eff: str | None = None
            end_eff: str | None = None
            if isinstance(start_param, str):
                start_eff = start_param.strip() or None
            elif start_param is None:
                start_eff = None
            else:
                start_eff = str(start_param).strip() or None if start_param is not None else None
            if isinstance(end_param, str):
                end_eff = end_param.strip() or None
            elif end_param is None:
                end_eff = None
            else:
                end_eff = str(end_param).strip() or None if end_param is not None else None
            # if not provided, use resolved selectors from override/default
            if start_eff is None and end_eff is None:
                try:
                    adapter_tmp = NovelPhoenixAdapter5()
                    eff = resolve_selectors_fn(adapter_tmp)
                    start_eff = eff.start
                    end_eff = eff.end
                except Exception:
                    start_eff = "div#chapter-content"
                    end_eff = None
            # get raw html from cache (AD-9) or fallback fetch
            raw_html: str | None = None
            try:
                import importlib as _il6
                _fmod = _il6.import_module("core.fetch")
                read_cache_fn = getattr(_fmod, "read_cache")
                raw_html = read_cache_fn(url_param)
            except Exception:
                raw_html = None
            if raw_html is None:
                # fallback: Core-owned polite raw fetch without cache (no write);
                # core.http mirrors adapters/_http.py politeness values without
                # importing an adapter module (core-no-adapters contract)
                try:
                    from core.http import _get as _http_get

                    resp = _http_get(url_param, timeout=12, retries=2)
                    raw_html = resp.text or ""
                except Exception as e:
                    return {"id": rid, "error": {"code": "LIST_FAILED", "message": f"no cache and fetch failed: {e}"}}
                if not raw_html:
                    return {"id": rid, "error": {"code": "LIST_FAILED", "message": "empty html"}}
            # clean via core.clean
            try:
                cleaned_html, cleaned_text = clean_html_fn(raw_html, start_eff, end_eff)
            except ValueError as ve:
                # invalid selector -> return error with code VALUE_ERROR for GUI muted
                return {"id": rid, "error": {"code": "VALUE_ERROR", "message": str(ve)}}
            except Exception as e:
                return {"id": rid, "error": {"code": "EXCEPTION", "message": str(e)}}
            # also provide original cleaned via default? For diff, original is raw stripped of scripts but not isolated? We return raw snippet for Original tab = raw limited
            original_text = ""
            try:
                from bs4 import BeautifulSoup as _BS
                _soup = _BS(raw_html, "lxml")
                for tag in _soup(["script", "style"]):
                    tag.decompose()
                original_text = _soup.get_text(separator=" ", strip=True)
                original_text = _re3.sub(r"\s+", " ", original_text).strip()
                # truncate original for preview? keep full for diff
            except Exception:
                original_text = ""
            # Apply filters once after selector isolation (AD-2) — preview chip + filtered view
            filtered_text = cleaned_text
            filtered_html = cleaned_html
            removed_count = 0
            filters_for_preview: list[dict] = []
            try:
                # load filters from store (sanitized)
                try:
                    _store_preview = load_store()
                    raw_filters = _store_preview.get("filters", [])
                    # lazy import to keep linter happy
                    import importlib as _il_f
                    _fmod_f = _il_f.import_module("core.filters")
                    _sanitize = getattr(_fmod_f, "sanitize_filters")
                    _apply = getattr(_fmod_f, "apply_filters")
                    filters_for_preview = _sanitize(raw_filters)
                    if filters_for_preview:
                        # HTML-aware filtering: remove matching <p>/blocks from cleaned_html, derive filtered_text from filtered_html
                        try:
                            _apply_html = getattr(_fmod_f, "apply_filters_to_html", None)
                            if _apply_html is not None:
                                filtered_html, removed_count = _apply_html(cleaned_html, filters_for_preview)
                                # derive filtered_text from filtered_html
                                try:
                                    from bs4 import BeautifulSoup as _BSF
                                    _soup_f = _BSF(filtered_html, "lxml") if filtered_html else None
                                    if _soup_f is not None:
                                        for _tag in _soup_f(["script", "style"]):
                                            _tag.decompose()
                                        ft = _soup_f.get_text(separator=" ", strip=True)
                                        ft = _re3.sub(r"\s+", " ", ft).strip() if ft else ""
                                        filtered_text = ft
                                    else:
                                        filtered_text = ""
                                except Exception:
                                    # fallback to text line filter
                                    filtered_text, removed_count = _apply(cleaned_text, filters_for_preview)
                            else:
                                filtered_text, removed_count = _apply(cleaned_text, filters_for_preview)
                                try:
                                    filtered_html_candidate, _ = _apply(cleaned_html, filters_for_preview)
                                    filtered_html = filtered_html_candidate
                                except Exception:
                                    filtered_html = cleaned_html
                        except ValueError:
                            raise
                        except Exception:
                            # fallback text filter
                            filtered_text, removed_count = _apply(cleaned_text, filters_for_preview)
                            filtered_html = cleaned_html
                except ValueError as ve:
                    # invalid regex in stored filters — surface as muted VALUE_ERROR but still return cleaned
                    return {"id": rid, "error": {"code": "VALUE_ERROR", "message": str(ve)}}
                except Exception:
                    # non-fatal: keep cleaned
                    filtered_text = cleaned_text
                    removed_count = 0
            except Exception:
                filtered_text = cleaned_text
            return {"id": rid, "result": {
                "url": url_param,
                "originalHtml": raw_html,
                "originalText": original_text[:8000],
                "html": cleaned_html,
                "text": cleaned_text,
                "filteredHtml": filtered_html,
                "filteredText": filtered_text,
                "removedCount": removed_count,
                "filters": filters_for_preview,
                "start": start_eff,
                "end": end_eff,
            }}

        if method == "saveSelectors":
            site = _resolve_site()
            if not site:
                # R3: explicit but unresolvable site/url must error — silently
                # falling back to novelphoenix would overwrite the default
                # site's overrides (data loss).
                if (isinstance(site_param, str) and site_param.strip()) or (
                    isinstance(url_param, str) and url_param.strip()
                ):
                    return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "invalid site or url"}}
                site = "novelphoenix.com"
            # host allowlist even for site-only save (prevent arbitrary override)
            allowed_site = site == "novelphoenix.com" or site.endswith(".novelphoenix.com")
            if not allowed_site:
                return {"id": rid, "error": {"code": "LIST_FAILED", "message": f"unsupported host {site}"}}
            # validate start/end selectors syntax by trying soup.select_one dummy (optional) — but delegate to clean validation
            s_start: str | None = None
            s_end: str | None = None
            if isinstance(start_param, str):
                s_start = start_param.strip() or None
            if isinstance(end_param, str):
                s_end = end_param.strip() or None
            # need at least one?
            if s_start is None and s_end is None:
                return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "start or end required"}}
            # validate selectors by test parse (invalid -> VALUE_ERROR)
            try:
                from bs4 import BeautifulSoup as _BS2
                _dummy = _BS2("<div></div>", "lxml")
                if s_start is not None:
                    _dummy.select_one(s_start)
                if s_end is not None:
                    _dummy.select_one(s_end)
            except Exception as e:
                return {"id": rid, "error": {"code": "VALUE_ERROR", "message": f"invalid selector: {e}"}}
            # validate host if url provided
            if isinstance(url_param, str) and url_param.strip():
                if not _re3.match(r"^https?://", url_param.strip(), _re3.I):
                    return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "url must be http(s)"}}
            try:
                from core.ports import Selectors as _Sel
                sel = _Sel(start=s_start, end=s_end)
                save_overrides_fn(site, sel)
                return {"id": rid, "result": {"saved": True, "site": site, "start": sel.start, "end": sel.end}}
            except Exception as e:
                return {"id": rid, "error": {"code": "EXCEPTION", "message": str(e)}}

        if method == "clearSelectors":
            site = _resolve_site()
            if not site:
                # R3: explicit but unresolvable site/url must error — silently
                # falling back to novelphoenix would delete the default site's
                # overrides (data loss).
                if (isinstance(site_param, str) and site_param.strip()) or (
                    isinstance(url_param, str) and url_param.strip()
                ):
                    return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "invalid site or url"}}
                site = "novelphoenix.com"
            allowed_site = site == "novelphoenix.com" or site.endswith(".novelphoenix.com")
            if not allowed_site:
                return {"id": rid, "error": {"code": "LIST_FAILED", "message": f"unsupported host {site}"}}
            try:
                cleared = clear_overrides_fn(site)
                return {"id": rid, "result": {"cleared": cleared, "site": site}}
            except Exception as e:
                return {"id": rid, "error": {"code": "EXCEPTION", "message": str(e)}}

    if method in ("getFilters", "addFilter", "removeFilter", "saveFilters", "updateFilter", "setFilters"):
            # Filters CRUD — plain contains + regex, persisted via store.json AD-10
            try:
                import importlib as _il_ff
                _fmod_ff = _il_ff.import_module("core.filters")
                _sanitize_ff = getattr(_fmod_ff, "sanitize_filters")
                _apply_ff = getattr(_fmod_ff, "apply_filters")
            except Exception as e:
                return {"id": rid, "error": {"code": "IMPORT_FAILED", "message": str(e)}}
            if method == "getFilters":
                try:
                    data = load_store()
                    raw = data.get("filters", [])
                    sanitized = _sanitize_ff(raw)
                    return {"id": rid, "result": {"filters": sanitized}}
                except Exception as e:
                    return {"id": rid, "error": {"code": "EXCEPTION", "message": str(e)}}
            if method == "addFilter":
                params = request.get("params") or {}
                if not isinstance(params, dict):
                    # allow pattern as string directly
                    params = {"pattern": str(params), "isRegex": False}
                pat = params.get("pattern", params.get("phrase", params.get("text", params.get("filter"))))
                is_regex = params.get("isRegex", params.get("is_regex", params.get("type") == "regex"))
                if isinstance(is_regex, str):
                    is_regex = is_regex.lower() in ("regex", "true", "1")
                is_regex = bool(is_regex) if is_regex is not None else False
                if not isinstance(pat, str) or not pat.strip():
                    return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "pattern must be non-empty"}}
                pat = pat.strip()
                if len(pat) > 200:
                    return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "pattern too long (max 200)"}}
                if is_regex:
                    try:
                        import re as _re_add
                        _re_add.compile(pat)
                    except Exception as e:
                        return {"id": rid, "error": {"code": "VALUE_ERROR", "message": f"invalid regex: {pat} {e}"}}
                data = load_store()
                raw = data.get("filters", [])
                sanitized = _sanitize_ff(raw)
                # dedup check
                key = f"{pat}|{is_regex}"
                for f in sanitized:
                    if f"{f.get('pattern')}|{f.get('isRegex')}" == key:
                        return {"id": rid, "result": {"filters": sanitized, "added": False, "reason": "duplicate"}}
                sanitized.append({"pattern": pat, "isRegex": is_regex})
                # cap 100 filters
                if len(sanitized) > 100:
                    return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "too many filters (max 100)"}}
                save_store({"filters": sanitized})
                return {"id": rid, "result": {"filters": sanitized, "added": True}}
            if method == "removeFilter":
                params = request.get("params") or {}
                idx = None
                pat_rm = None
                is_regex_rm = None
                if isinstance(params, dict):
                    # allow index
                    idx = params.get("index", params.get("idx", params.get("i")))
                    pat_rm = params.get("pattern", params.get("phrase"))
                    is_regex_rm = params.get("isRegex", params.get("is_regex"))
                    if isinstance(is_regex_rm, str):
                        is_regex_rm = is_regex_rm.lower() in ("regex", "true", "1")
                elif isinstance(params, (int, float)):
                    idx = params
                try:
                    data = load_store()
                    raw = data.get("filters", [])
                    sanitized = _sanitize_ff(raw)
                    if idx is not None:
                        try:
                            idx_i = int(idx)  # type: ignore
                        except Exception:
                            return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "index must be integer"}}
                        if idx_i < 0 or idx_i >= len(sanitized):
                            return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "index out of range"}}
                        sanitized.pop(idx_i)
                        save_store({"filters": sanitized})
                        return {"id": rid, "result": {"filters": sanitized, "removed": True}}
                    if pat_rm and isinstance(pat_rm, str):
                        pat_rm = pat_rm.strip()
                        is_regex_rm = bool(is_regex_rm) if is_regex_rm is not None else None
                        new_list: list[dict] = []
                        removed = False
                        for f in sanitized:
                            if f.get("pattern") == pat_rm and (is_regex_rm is None or f.get("isRegex") == bool(is_regex_rm)):
                                removed = True
                                continue
                            new_list.append(f)
                        if not removed:
                            return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "filter not found"}}
                        save_store({"filters": new_list})
                        return {"id": rid, "result": {"filters": new_list, "removed": True}}
                    return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "index or pattern required"}}
                except Exception as e:
                    return {"id": rid, "error": {"code": "EXCEPTION", "message": str(e)}}
            if method in ("saveFilters", "setFilters", "updateFilter"):
                params = request.get("params") or {}
                filters_in: Any = None
                if isinstance(params, dict):
                    filters_in = params.get("filters", params.get("list", params.get("items")))
                    if filters_in is None and "pattern" in params:
                        # single filter update? treat as save single list
                        filters_in = [params]
                elif isinstance(params, list):
                    filters_in = params
                else:
                    filters_in = []
                if filters_in is None:
                    filters_in = []
                if not isinstance(filters_in, list):
                    return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "filters must be list"}}
                if len(filters_in) > 100:
                    return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "too many filters (max 100)"}}
                # validate each
                sanitized: list[dict] = []
                seen: set[str] = set()
                for f in filters_in:
                    if not isinstance(f, dict):
                        return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "each filter must be object"}}
                    pat2 = f.get("pattern", f.get("phrase", f.get("text")))
                    is_r2 = f.get("isRegex", f.get("is_regex", f.get("type") == "regex"))
                    if isinstance(is_r2, str):
                        is_r2 = is_r2.lower() in ("regex", "true", "1")
                    is_r2 = bool(is_r2) if is_r2 is not None else False
                    if not isinstance(pat2, str) or not pat2.strip():
                        return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "pattern must be non-empty"}}
                    pat2 = pat2.strip()
                    if len(pat2) > 200:
                        return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "pattern too long (max 200)"}}
                    if is_r2:
                        try:
                            import re as _re_save
                            _re_save.compile(pat2)
                        except Exception as e:
                            return {"id": rid, "error": {"code": "VALUE_ERROR", "message": f"invalid regex: {pat2} {e}"}}
                    key2 = f"{pat2}|{is_r2}"
                    if key2 in seen:
                        continue
                    seen.add(key2)
                    sanitized.append({"pattern": pat2, "isRegex": is_r2})
                save_store({"filters": sanitized})
                return {"id": rid, "result": {"filters": sanitized, "saved": True}}

    # EPUB Assembly + Result card + epubcheck — Story 2.4
    if method in ("buildEpub", "build_epub", "buildEPUB"):
        # AD-1: dynamic import preserves GUI->Core->Port->Adapter
        import re as _re_epub
        from urllib.parse import urlparse as _up_epub

        def _site_from_url_epub(u: str) -> str | None:
            try:
                p = _up_epub(u.strip())
                host = (p.hostname or "").lower().rstrip(".")
                if host and host.startswith("www."):
                    host = host[4:]
                return host or None
            except Exception:
                return None

        params = request.get("params")
        # support multiple param shapes: dict with novelUrl/coverUrl/title/author/from/to/outputDir/urls
        novelUrl: Any = None
        title_p: Any = None
        author_p: Any = None
        coverUrl_p: Any = None
        from_p: Any = None
        to_p: Any = None
        outputDir_p: Any = None
        urls_p: Any = None
        # also support generic filters param? core loads from store, so ignore
        if isinstance(params, dict):
            novelUrl = params.get("novelUrl", params.get("novel_url", params.get("novelURL", params.get("url", params.get("link")))))
            title_p = params.get("title", params.get("bookTitle", params.get("book_title")))
            author_p = params.get("author", params.get("bookAuthor", params.get("authorName")))
            coverUrl_p = params.get("coverUrl", params.get("cover_url", params.get("cover", params.get("coverURL"))))
            from_p = params.get("from", params.get("from_idx", params.get("fromIdx", params.get("selection_from", params.get("start")))))
            to_p = params.get("to", params.get("to_idx", params.get("toIdx", params.get("selection_to", params.get("end")))))
            outputDir_p = params.get("outputDir", params.get("output_dir", params.get("output", params.get("dir"))))
            urls_p = params.get("urls", params.get("chapterUrls", params.get("chapter_urls", params.get("links"))))
            # if novelUrl still None but urls contains first url, infer?
            if isinstance(urls_p, str):
                urls_p = [urls_p]
            if isinstance(urls_p, dict):
                urls_p = [urls_p]
            # also handle single url param
            if novelUrl is None and isinstance(params.get("url"), str):
                novelUrl = params.get("url")
        elif isinstance(params, str):
            novelUrl = params
        else:
            novelUrl = None

        if isinstance(novelUrl, str):
            novelUrl = novelUrl.strip()
        if not isinstance(novelUrl, str) or not novelUrl:
            return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "url must be non-empty"}}
        if not _re_epub.match(r"^https?://", novelUrl, _re_epub.I):
            return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "url must be http(s)"}}
        try:
            parsed_epub = _up_epub(novelUrl)
            host_epub = (parsed_epub.hostname or "").lower().rstrip(".")
            if not host_epub:
                return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "url must contain host"}}
            allowed_epub = host_epub == "novelphoenix.com" or host_epub == "www.novelphoenix.com" or host_epub.endswith(".novelphoenix.com")
            if not allowed_epub:
                return {"id": rid, "error": {"code": "LIST_FAILED", "message": f"unsupported host {host_epub}"}}
        except Exception as e:
            return {"id": rid, "error": {"code": "VALUE_ERROR", "message": str(e)}}

        # sanitize title/author ≤200 chars
        if isinstance(title_p, str):
            title_p = title_p.strip()
            if len(title_p) > 200:
                title_p = title_p[:200]
            if not title_p:
                title_p = None
        else:
            title_p = None
            # fallback title from store? keep None -> slug book
        if isinstance(author_p, str):
            author_p = author_p.strip()
            if len(author_p) > 200:
                author_p = author_p[:200]
            if not author_p:
                author_p = None
        else:
            author_p = None
        # cover_url sanitization
        if isinstance(coverUrl_p, str):
            coverUrl_p = coverUrl_p.strip()
            if not coverUrl_p:
                coverUrl_p = None
            elif coverUrl_p.lower().startswith("data:"):
                # keep but will be skipped in epub build (data-url guard)
                pass
            elif not _re_epub.match(r"^https?://", coverUrl_p, _re_epub.I):
                coverUrl_p = None
            elif len(coverUrl_p) > 500:
                coverUrl_p = coverUrl_p[:500]
        else:
            coverUrl_p = None

        # from/to parsing with clamp — keep raw for logging
        def _parse_epub_idx_raw(v):
            if v is None or v == "":
                return None
            try:
                return int(v)  # type: ignore
            except Exception:
                return None

        def _parse_epub_idx(v, default=None):
            iv = _parse_epub_idx_raw(v)
            if iv is None:
                return default
            if iv < 1:
                return 1
            return max(1, min(iv, 100000))

        raw_from = _parse_epub_idx_raw(from_p)
        raw_to = _parse_epub_idx_raw(to_p)
        from_idx = _parse_epub_idx(from_p, 1)
        to_idx = _parse_epub_idx(to_p, None)
        if from_idx is None:
            from_idx = 1
        if to_idx is None:
            to_idx = from_idx
        # handle swap if inverted (even before N)
        if from_idx > to_idx:
            from_idx, to_idx = to_idx, from_idx
            if raw_from is not None and raw_to is not None:
                raw_from, raw_to = raw_to, raw_from

        # Determine N via _CHAPTER_CACHE or adapter listChapters for clamp
        N: int | None = None
        chapter_infos_for_clamp: Any = None
        try:
            cache_key_epub = _normalize_cache_key(novelUrl)
            if cache_key_epub in _CHAPTER_CACHE:
                cached_epub = _CHAPTER_CACHE[cache_key_epub]
                if isinstance(cached_epub, list):
                    N = len(cached_epub)
                    chapter_infos_for_clamp = cached_epub
        except Exception:
            pass
        if N is None:
            # try adapter listChapters without network fallback? best-effort
            try:
                import importlib as _il_epub
                _mod_epub = _il_epub.import_module("adapters.novelphoenix")
                AdapterEp = getattr(_mod_epub, "NovelPhoenixAdapter")
                adapter_ep = AdapterEp()
                lst_ep = adapter_ep.listChapters(novelUrl)
                if lst_ep and isinstance(lst_ep, (list, tuple)):
                    N = len(lst_ep)
                    chapter_infos_for_clamp = list(lst_ep)
                    # cache it for future offline
                    try:
                        if len(_CHAPTER_CACHE) >= 20:
                            _CHAPTER_CACHE.pop(next(iter(_CHAPTER_CACHE)))
                    except Exception:
                        pass
                    try:
                        _CHAPTER_CACHE[cache_key_epub] = [
                            {"index": getattr(ci, "index", i + 1), "title": getattr(ci, "title", ""), "url": getattr(ci, "url", "")}
                            for i, ci in enumerate(lst_ep)
                        ]
                    except Exception:
                        pass
            except Exception:
                N = None

        # clamp to N if known — use raw for original log to show 0->1
        logs_epub: List[str] = []
        if N is not None:
            # orig for log is raw if available else from_idx
            orig_from_log = raw_from if raw_from is not None else from_idx
            orig_to_log = raw_to if raw_to is not None else to_idx
            clamped_from = max(1, min(from_idx, N))
            clamped_to = max(1, min(to_idx, N))
            if clamped_from > clamped_to:
                clamped_from, clamped_to = clamped_to, clamped_from
            if clamped_from != orig_from_log or clamped_to != orig_to_log:
                logs_epub.append(f"clamped {orig_from_log}->{clamped_from}, {orig_to_log}->{clamped_to}")
            from_idx, to_idx = clamped_from, clamped_to
            # also show raw clamp if from was 0? ensure log shows 0->1
            # if raw was 0 and clamped is 1, above handles
        else:
            if (to_idx - from_idx + 1) > 500:
                return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "range too large (max 500 without cache)"}}
            # still ensure within 1..100000 and swap already done

        # Handle urls_p normalization
        desired_urls_norm: List[str] | None = None
        if isinstance(urls_p, (list, tuple)) and len(urls_p) > 0:
            cleaned_urls: List[str] = []
            for u in urls_p:  # type: ignore
                if isinstance(u, str) and u.strip():
                    cleaned_urls.append(u.strip())
                elif isinstance(u, dict):
                    uu = u.get("url") or u.get("link") or u.get("href")
                    if isinstance(uu, str) and uu.strip():
                        cleaned_urls.append(uu.strip())
            # dedup preserve order
            try:
                cleaned_urls = list(dict.fromkeys(cleaned_urls))
            except Exception:
                pass
            if not cleaned_urls:
                return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "urls empty after trim/dedup"}}
            # validate each url host allowlist
            for u in cleaned_urls:
                if not _re_epub.match(r"^https?://", u, _re_epub.I):
                    return {"id": rid, "error": {"code": "VALUE_ERROR", "message": f"url must be http(s) {u}"}}
                try:
                    p2 = _up_epub(u)
                    h2 = (p2.hostname or "").lower().rstrip(".")
                    if not h2:
                        return {"id": rid, "error": {"code": "VALUE_ERROR", "message": f"url must contain host {u}"}}
                    allowed2 = h2 == "novelphoenix.com" or h2 == "www.novelphoenix.com" or h2.endswith(".novelphoenix.com")
                    if not allowed2:
                        return {"id": rid, "error": {"code": "LIST_FAILED", "message": f"unsupported host {h2}"}}
                except Exception as e:
                    return {"id": rid, "error": {"code": "VALUE_ERROR", "message": str(e)}}
            # If cleaned urls length mismatch with from/to, we keep as is but ensure chapter_count = len
            # For filename we keep from_idx/to_idx as clamped above, but also could infer from urls length?
            desired_urls_norm = cleaned_urls
            # If urls provided, chapter count is len(desired_urls_norm), but from/to remain for naming
            # Ensure from/to reflect actual urls count if N unknown? Keep original clamped.
        else:
            desired_urls_norm = None

        # If desired_urls_norm is None, we will derive via chapter_infos_for_clamp or synthetic inside epub
        # But we need to do CACHE_MISS check before calling epub if we have derived urls
        # For urls provided, check missing now
        if desired_urls_norm is not None:
            # check missing via core.fetch.read_cache
            try:
                import importlib as _il_fetch_epub
                _fmod_epub = _il_fetch_epub.import_module("core.fetch")
                read_cache_epub = getattr(_fmod_epub, "read_cache")
            except Exception as e:
                return {"id": rid, "error": {"code": "IMPORT_FAILED", "message": str(e)}}
            missing_urls: List[str] = []
            for u in desired_urls_norm:
                try:
                    rc = read_cache_epub(u)
                except Exception:
                    rc = None
                if rc is None:
                    missing_urls.append(u)
            if missing_urls:
                for mu in missing_urls:
                    logs_epub.append(f"cache miss {mu}")
                return {"id": rid, "error": {"code": "CACHE_MISS", "message": f"cache miss {len(missing_urls)}", "missing": missing_urls}}
        else:
            # derive desired via chapter_infos_for_clamp or synthetic for missing check?
            # We'll let core.epub.build_epub handle missing check, but we can pre-check by asking fetch for each index url
            # Build synthetic list for pre-check
            synthetic_for_check: List[str] = []
            if chapter_infos_for_clamp is not None and isinstance(chapter_infos_for_clamp, list):
                # map index->url
                idx_to_url_check: Dict[int, str] = {}
                for item in chapter_infos_for_clamp:  # type: ignore
                    try:
                        if isinstance(item, dict):
                            idx = item.get("index")
                            url = item.get("url") or item.get("link")
                        else:
                            idx = getattr(item, "index", None)
                            url = getattr(item, "url", None)
                        if idx is not None and url:
                            idx_to_url_check[int(idx)] = str(url).strip()
                    except Exception:
                        continue
                for idx in range(from_idx, to_idx + 1):
                    if idx in idx_to_url_check:
                        synthetic_for_check.append(idx_to_url_check[idx])
                    else:
                        synthetic_for_check.append(f"{novelUrl.rstrip('/')}/chapter/{idx}")
            else:
                for idx in range(from_idx, to_idx + 1):
                    synthetic_for_check.append(f"{novelUrl.rstrip('/')}/chapter/{idx}")
            # check missing
            try:
                import importlib as _il_fetch2
                _fmod2 = _il_fetch2.import_module("core.fetch")
                read_cache2 = getattr(_fmod2, "read_cache")
            except Exception as e:
                return {"id": rid, "error": {"code": "IMPORT_FAILED", "message": str(e)}}
            missing2: List[str] = []
            for u in synthetic_for_check:
                try:
                    rc2 = read_cache2(u)
                except Exception:
                    rc2 = None
                if rc2 is None:
                    missing2.append(u)
            if missing2:
                for mu in missing2:
                    logs_epub.append(f"cache miss {mu}")
                return {"id": rid, "error": {"code": "CACHE_MISS", "message": f"cache miss {len(missing2)}", "missing": missing2}}

        # Load filters from store (core filters)
        # outputDir handling: if not provided, use ./output
        if isinstance(outputDir_p, str):
            outputDir_p = outputDir_p.strip() or None
            if isinstance(outputDir_p, str) and outputDir_p:
                if ".." in outputDir_p or "\0" in outputDir_p:
                    return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "outputDir invalid"}}
        elif outputDir_p is not None and not isinstance(outputDir_p, (str, Path)):
            outputDir_p = str(outputDir_p)
            if ".." in outputDir_p or "\0" in outputDir_p:
                return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "outputDir invalid"}}

        # Dynamic import core.epub build
        try:
            import importlib as _il_epub_build
            _epub_mod = _il_epub_build.import_module("core.epub")
            build_epub_fn = getattr(_epub_mod, "build_epub")
        except Exception as e:
            return {"id": rid, "error": {"code": "IMPORT_FAILED", "message": str(e)}}

        # KeepEPUB from store (AD-10) — file still written per build, but reflect
        try:
            store_keep = load_store()
            keep_epub_val = store_keep.get("keepEPUB", True)
        except Exception:
            keep_epub_val = True

        try:
            # call build_epub with chapter_urls if we have desired_urls_norm
            result_epub = build_epub_fn(
                novel_url=novelUrl,
                from_idx=from_idx,
                to_idx=to_idx,
                title=title_p,
                author=author_p,
                cover_url=coverUrl_p,
                output_dir=outputDir_p or "output",
                filters=None,  # let epub load from store
                chapter_urls=desired_urls_norm,
            )
            # result_epub contains path,size,chapter_count,epubcheck_ok,messages,logs
            # merge our clamp logs
            if logs_epub:
                # prepend clamp logs
                existing_logs = result_epub.get("logs", [])
                result_epub["logs"] = logs_epub + existing_logs
            # ensure keepEPUB reflected
            result_epub["keepEPUB"] = bool(keep_epub_val)
            # Map per-chapter cleaning->done for GUI via logs already
            # Return result with badge handling
            return {"id": rid, "result": result_epub}
        except Exception as e:
            code = getattr(e, "code", None)
            if code == "CACHE_MISS":
                # try to extract missing from exception
                msg = str(e)
                # try to get missing attribute if exists
                missing_attr = getattr(e, "missing", None)
                if missing_attr is None:
                    # fallback to synthetic missing already computed?
                    missing_attr = []
                return {"id": rid, "error": {"code": "CACHE_MISS", "message": msg, "missing": missing_attr if isinstance(missing_attr, list) else []}}
            if isinstance(e, ValueError):
                return {"id": rid, "error": {"code": "VALUE_ERROR", "message": str(e)}}
            if code == "LIST_FAILED":
                return {"id": rid, "error": {"code": "LIST_FAILED", "message": str(e)}}
            # epubcheck dirty is not error, should have been returned as ok false
            # For other exceptions, map to EXCEPTION
            msg2 = str(e)
            if "VALUE_ERROR" in msg2:
                return {"id": rid, "error": {"code": "VALUE_ERROR", "message": msg2}}
            if "CACHE_MISS" in msg2:
                # H/M1: always attach missing list so GUI can highlight chapters
                miss = getattr(e, "missing", None)
                return {"id": rid, "error": {"code": "CACHE_MISS", "message": msg2, "missing": miss if isinstance(miss, list) else []}}
            return {"id": rid, "error": {"code": "EXCEPTION", "message": msg2}}

    if method in ("getEpubStatus", "get_epub_status"):
        params = request.get("params") or {}
        if not isinstance(params, dict):
            params = {}
        novelUrl = params.get("novelUrl", params.get("novel_url", params.get("url")))
        from_p = params.get("from", params.get("from_idx", params.get("fromIdx")))
        to_p = params.get("to", params.get("to_idx", params.get("toIdx")))
        outputDir_p = params.get("outputDir", params.get("output_dir", params.get("output")))
        if isinstance(outputDir_p, str) and outputDir_p:
            if ".." in outputDir_p or "\0" in outputDir_p:
                return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "outputDir invalid"}}
        # try to locate latest epub file for that novel
        try:
            import re as _re_stat
            from pathlib import Path as _Path_stat

            base_dir = None
            try:
                import importlib as _il_out_stat

                _tts_out_stat = _il_out_stat.import_module("core.tts")
                base_dir = getattr(_tts_out_stat, "resolve_output_dir")(outputDir_p, ensure=False)
            except Exception:
                base_dir = None
            if base_dir is None:
                base_dir = _Path_stat(outputDir_p) if isinstance(outputDir_p, (str, _Path_stat)) and str(outputDir_p).strip() else _Path_stat("output")
            if not base_dir.exists():
                return {"id": rid, "result": {"exists": False, "path": None}}
            # Find most recent .epub file
            candidates = list(base_dir.glob("*.epub"))
            if not candidates:
                # also check subdirs?
                candidates = list(base_dir.rglob("*.epub"))
            if not candidates:
                return {"id": rid, "result": {"exists": False, "path": None}}
            # filter by novelUrl slug if possible
            def _novel_tokens(url: object) -> list[str]:
                try:
                    import re as _re_tok
                    from urllib.parse import urlparse as _up_tok

                    s = str(url or "").strip().lower()
                    if not s:
                        return []
                    # last path segment, e.g. /novel/123-lord-of-mysteries -> lord of mysteries
                    path = _up_tok(s).path or s
                    seg = path.rstrip("/").rsplit("/", 1)[-1]
                    seg = _re_tok.sub(r"[^a-z0-9]+", " ", seg).strip()
                    toks = [t for t in seg.split() if t and not t.isdigit() and len(t) > 2]
                    # drop generic words
                    toks = [t for t in toks if t not in ("novel", "book", "html")]
                    return toks[:4]
                except Exception:
                    return []

            def _range_of(p_name: str) -> tuple[int | None, int | None]:
                try:
                    import re as _re_rng

                    m = _re_rng.search(r"_chapters_(\d+)_to_(\d+)", p_name)
                    if m:
                        return int(m.group(1)), int(m.group(2))
                    return None, None
                except Exception:
                    return None, None

            try:
                pool = list(candidates)
                toks = _novel_tokens(novelUrl)
                if toks:
                    scored: list[tuple[int, float, object]] = []
                    for c in pool:
                        try:
                            stem = c.stem.lower()
                            hits = sum(1 for t in toks if t in stem)
                            scored.append((hits, c.stat().st_mtime, c))
                        except OSError:
                            continue
                    best_hits = max((s[0] for s in scored), default=0)
                    if best_hits > 0:
                        pool = [c for h, _, c in scored if h == best_hits]
                # optional range filter when from/to supplied and filename carries range
                try:
                    fp = int(from_p) if from_p is not None and str(from_p).strip() != "" else None
                    tp = int(to_p) if to_p is not None and str(to_p).strip() != "" else None
                except Exception:
                    fp, tp = None, None
                if fp is not None and tp is not None:
                    ranged = []
                    for c in pool:
                        a, b = _range_of(c.name)
                        if a is not None and b is not None and not (b < fp or a > tp):
                            ranged.append(c)
                    if ranged:
                        pool = ranged
                latest = max(pool, key=lambda p: p.stat().st_mtime)
                size = latest.stat().st_size
            except OSError:
                return {"id": rid, "result": {"exists": False, "path": None}}
            # Try to check epub validity
            try:
                import importlib as _il_stat
                _epub_mod_stat = _il_stat.import_module("core.epub")
                run_check = getattr(_epub_mod_stat, "run_epubcheck")
                ok, msgs = run_check(latest)
            except Exception as e:
                ok, msgs = False, [f"epubcheck failed: {e}"]
            return {"id": rid, "result": {"exists": True, "path": str(latest), "size": size, "epubcheck_ok": ok, "messages": msgs}}
        except Exception as e:
            return {"id": rid, "error": {"code": "EXCEPTION", "message": str(e)}}

    if method in ("localVoices", "local_voices", "listLocalVoices"):
        try:
            from core.tts_local import list_local_voices

            return {"id": rid, "result": list_local_voices()}
        except Exception as e:
            return {"id": rid, "error": {"code": "EXCEPTION", "message": str(e)}}

    if method in ("downloadLocalVoice", "download_local_voice"):
        params = request.get("params") or {}
        if not isinstance(params, dict):
            return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "params must be object"}}
        voice_p = params.get("voice", params.get("id"))
        voice_p = voice_p.strip() if isinstance(voice_p, str) else ""
        if not voice_p:
            return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "voice must be non-empty"}}
        # force=true re-downloads (escape hatch for present-but-corrupt models)
        def _flag(value: Any) -> bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return value != 0
            if isinstance(value, str):
                return value.strip().lower() not in ("", "0", "false", "no", "off")
            return False

        force_p = _flag(params.get("force", False)) or _flag(params.get("forceRedownload", False))

        def _emit_voice_log(line: str) -> None:
            if emit_fn:
                try:
                    emit_fn("logLine", {"line": line})
                except Exception:
                    pass

        try:
            from core.tts_local import download_local_voice

            result = download_local_voice(voice_p, on_log=_emit_voice_log, force=force_p)
            return {"id": rid, "result": result}
        except ValueError as e:
            return {"id": rid, "error": {"code": "VALUE_ERROR", "message": str(e)}}
        except RuntimeError as e:
            return {"id": rid, "error": {"code": "DOWNLOAD_FAILED", "message": str(e)}}
        except Exception as e:
            return {"id": rid, "error": {"code": "EXCEPTION", "message": str(e)}}

    if method in ("buildAudio", "build_audio", "buildAudiobook"):
        import re as _re_audio
        from urllib.parse import urlparse as _up_audio

        params = request.get("params") or {}
        if not isinstance(params, dict):
            return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "params must be object"}}
        novelUrl = params.get("novelUrl", params.get("novel_url", params.get("url", params.get("novel"))))
        from_p = params.get("from", params.get("from_idx", params.get("fromIdx")))
        to_p = params.get("to", params.get("to_idx", params.get("toIdx", params.get("end"))))
        title_p = params.get("title")
        outputDir_p = params.get("outputDir", params.get("output_dir", params.get("output")))
        urls_p = params.get("urls", params.get("chapterUrls", params.get("chapter_urls")))
        voice_p = params.get("voice", params.get("voiceName"))
        rate_p = params.get("rate")
        engine_p = params.get("engine")
        local_voice_p = params.get("localVoice", params.get("local_voice"))
        bitrate_p = params.get("audioBitrate", params.get("audio_bitrate", params.get("bitrate")))
        parallel_p = params.get("parallel")
        retries_p = params.get("retries")
        chunk_p = params.get("chunkSize", params.get("chunk_size", params.get("chunk-size")))
        format_p = params.get("format", params.get("ext", params.get("audioFormat")))
        keep_parts_p = params.get("keepParts", params.get("keep_parts", False))

        if isinstance(novelUrl, str):
            novelUrl = novelUrl.strip()
        if not isinstance(novelUrl, str) or not novelUrl:
            return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "url must be non-empty"}}
        if not _re_audio.match(r"^https?://", novelUrl, _re_audio.I):
            return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "url must be http(s)"}}
        try:
            parsed_audio = _up_audio(novelUrl)
            host_audio = (parsed_audio.hostname or "").lower().rstrip(".")
            if not host_audio:
                return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "url must contain host"}}
            if not (host_audio == "novelphoenix.com" or host_audio == "www.novelphoenix.com" or host_audio.endswith(".novelphoenix.com")):
                return {"id": rid, "error": {"code": "LIST_FAILED", "message": f"unsupported host {host_audio}"}}
        except Exception as e:
            return {"id": rid, "error": {"code": "VALUE_ERROR", "message": str(e)}}

        if isinstance(outputDir_p, str):
            outputDir_p = outputDir_p.strip() or None
            if isinstance(outputDir_p, str) and outputDir_p and (".." in outputDir_p or "\0" in outputDir_p):
                return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "outputDir invalid"}}
        elif outputDir_p is not None:
            try:
                outputDir_p = str(outputDir_p)
            except Exception:
                outputDir_p = None

        # store-backed TTS defaults (Settings owns voice/parallel/chunk/retries)
        try:
            store_audio = load_store()
        except Exception:
            store_audio = {}
        if not isinstance(voice_p, str) or not voice_p.strip():
            try:
                voice_p = str(store_audio.get("voice", "en-US-AndrewNeural"))
            except Exception:
                voice_p = "en-US-AndrewNeural"
        if bitrate_p is None:
            try:
                bitrate_p = str(store_audio.get("audioBitrate", "32k")) if isinstance(store_audio, dict) else "32k"
            except Exception:
                bitrate_p = "32k"
        # fail fast on garbage bitrate (audio.py re-validates authoritatively)
        _br_m = _re_audio.fullmatch(r"\s*(\d+)\s*k\s*", str(bitrate_p), _re_audio.I) if bitrate_p is not None else None
        if not _br_m or not (16 <= int(_br_m.group(1)) <= 128):
            return {"id": rid, "error": {"code": "VALUE_ERROR", "message": f"invalid audioBitrate {bitrate_p}"}}
        bitrate_p = f"{int(_br_m.group(1))}k"
        if parallel_p is None:
            parallel_p = store_audio.get("parallel", 3) if isinstance(store_audio, dict) else 3
        if retries_p is None:
            retries_p = store_audio.get("retries", 5) if isinstance(store_audio, dict) else 5
        if rate_p is None:
            try:
                rate_p = store_audio.get("rate", "+0%") if isinstance(store_audio, dict) else "+0%"
            except Exception:
                rate_p = "+0%"
        # fail fast on garbage rate (build_audio re-validates via normalize)
        _rate_m = _re_audio.match(r"^\s*[+-]?\d+%?\s*$", str(rate_p)) if rate_p is not None else None
        if not _rate_m:
            return {"id": rid, "error": {"code": "VALUE_ERROR", "message": f"invalid rate {rate_p}"}}
        try:
            _rate_num = int(str(rate_p).strip().rstrip("%"))
        except Exception:
            return {"id": rid, "error": {"code": "VALUE_ERROR", "message": f"invalid rate {rate_p}"}}
        _rate_num = max(-100, min(100, _rate_num))
        rate_p = f"{_rate_num:+d}%"
        if engine_p is None:
            try:
                engine_p = store_audio.get("engine", "auto") if isinstance(store_audio, dict) else "auto"
            except Exception:
                engine_p = "auto"
        engine_p = engine_p.strip().lower() if isinstance(engine_p, str) else "auto"
        if engine_p not in ("auto", "edge", "local"):
            return {"id": rid, "error": {"code": "VALUE_ERROR", "message": f"invalid engine {engine_p}"}}
        if local_voice_p is None:
            try:
                local_voice_p = store_audio.get("localVoice") if isinstance(store_audio, dict) else None
            except Exception:
                local_voice_p = None
        local_voice_p = local_voice_p.strip() if isinstance(local_voice_p, str) else None
        if local_voice_p == "":
            local_voice_p = None
        if local_voice_p is not None:
            from core.tts_local import LOCAL_VOICES as _LOCAL_VOICES

            if local_voice_p not in _LOCAL_VOICES:
                return {"id": rid, "error": {"code": "VALUE_ERROR", "message": f"unknown local voice {local_voice_p}"}}
        if engine_p == "local":
            # fail fast: download is a deliberate Settings action, not a build side effect
            from core.tts_local import (
                DEFAULT_LOCAL_VOICE as _DEFAULT_LOCAL_VOICE,
                _local_unavailable_message as _local_unavail_msg,
                local_voice_ready as _local_voice_ready,
            )

            _check_voice = local_voice_p or _DEFAULT_LOCAL_VOICE
            if not _local_voice_ready(_check_voice):
                return {"id": rid, "error": {"code": "VALUE_ERROR", "message": _local_unavail_msg(_check_voice)}}
        if chunk_p is None:
            try:
                chunk_p = (store_audio.get("chunk-size", 3500) if isinstance(store_audio, dict) else 3500)
            except Exception:
                chunk_p = 3500
        # R3: fail loudly on garbage/out-of-range chunk size — mirrors the CLI
        # guard; Edge TTS truncates overlong requests (silent audio gaps).
        try:
            chunk_p = int(chunk_p)
        except Exception:
            return {"id": rid, "error": {"code": "VALUE_ERROR", "message": f"invalid chunkSize {chunk_p!r}"}}
        if chunk_p < 500 or chunk_p > 5000:
            return {"id": rid, "error": {"code": "VALUE_ERROR", "message": f"chunkSize {chunk_p} out of range 500..5000 (Edge truncates above 5000)"}}
        try:
            keep_parts_bool = bool(keep_parts_p) if not isinstance(keep_parts_p, str) else keep_parts_p.strip().lower() in ("1", "true", "yes")
        except Exception:
            keep_parts_bool = False

        # normalize urls (same shape as buildEpub)
        desired_urls_norm: List[str] | None = None
        if isinstance(urls_p, (list, tuple)) and len(urls_p) > 0:
            cleaned_urls: List[str] = []
            for u in urls_p:  # type: ignore[union-attr]
                if isinstance(u, str) and u.strip():
                    cleaned_urls.append(u.strip())
                elif isinstance(u, dict):
                    uu = u.get("url") or u.get("link") or u.get("href")
                    if isinstance(uu, str) and uu.strip():
                        cleaned_urls.append(uu.strip())
            try:
                cleaned_urls = list(dict.fromkeys(cleaned_urls))
            except Exception:
                pass
            if not cleaned_urls:
                return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "urls empty after trim/dedup"}}
            if len(cleaned_urls) > 1000:
                return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "too many urls (max 1000)"}}
            for u in cleaned_urls:
                if not _re_audio.match(r"^https?://", u, _re_audio.I):
                    return {"id": rid, "error": {"code": "VALUE_ERROR", "message": f"url must be http(s) {u}"}}
            desired_urls_norm = cleaned_urls

        # CACHE_MISS pre-check for explicit urls (fail fast with missing list)
        if desired_urls_norm is not None:
            try:
                import importlib as _il_fetch_audio

                _fmod_audio = _il_fetch_audio.import_module("core.fetch")
                read_cache_audio = getattr(_fmod_audio, "read_cache")
            except Exception as e:
                return {"id": rid, "error": {"code": "IMPORT_FAILED", "message": str(e)}}
            missing_audio: List[str] = []
            for u in desired_urls_norm:
                try:
                    rc_audio = read_cache_audio(u)
                except Exception:
                    rc_audio = None
                if rc_audio is None:
                    missing_audio.append(u)
            if missing_audio:
                return {"id": rid, "error": {"code": "CACHE_MISS", "message": f"cache miss {len(missing_audio)}", "missing": missing_audio}}

        try:
            import importlib as _il_audio

            _audio_mod = _il_audio.import_module("core.audio")
            build_audio_fn = getattr(_audio_mod, "build_audio")
        except Exception as e:
            return {"id": rid, "error": {"code": "IMPORT_FAILED", "message": str(e)}}

        def _emit_audio_part(payload: dict) -> None:
            if emit_fn:
                try:
                    emit_fn("partStatus", payload)
                except Exception:
                    pass

        def _emit_audio_log(line: str) -> None:
            if emit_fn:
                try:
                    emit_fn("logLine", {"line": line})
                except Exception:
                    pass

        def _emit_audio_progress(done: int, total: int) -> None:
            if emit_fn:
                try:
                    emit_fn("logLine", {"line": f"progress: {done}/{total} TTS part job(s) complete"})
                except Exception:
                    pass

        def _emit_audio_phase(payload: dict) -> None:
            if emit_fn:
                try:
                    emit_fn("mergeProgress", payload)
                except Exception:
                    pass

        try:
            result_audio = build_audio_fn(
                novel_url=novelUrl,
                from_idx=from_p,
                to_idx=to_p,
                title=title_p if isinstance(title_p, str) else None,
                output_dir=outputDir_p or "output",
                filters=None,
                chapter_urls=desired_urls_norm,
                voice=voice_p,
                rate=rate_p,
                engine=engine_p,
                local_voice=local_voice_p,
                parallel=parallel_p,
                retries=retries_p,
                chunk_size=chunk_p,
                audio_format=format_p or "m4b",
                audio_bitrate=bitrate_p,
                keep_parts=keep_parts_bool,
                keep_mp3=None,
                on_part_status=_emit_audio_part,
                on_log=_emit_audio_log,
                on_progress=_emit_audio_progress,
                on_phase=_emit_audio_phase,
            )
            if emit_fn:
                try:
                    emit_fn("done", {"result": "ok"})
                except Exception:
                    pass
            return {"id": rid, "result": result_audio}
        except Exception as e:
            code = getattr(e, "code", None)
            if code == "CACHE_MISS":
                missing_attr = getattr(e, "missing", None)
                return {"id": rid, "error": {"code": "CACHE_MISS", "message": str(e), "missing": missing_attr if isinstance(missing_attr, list) else []}}
            if isinstance(e, ValueError):
                return {"id": rid, "error": {"code": "VALUE_ERROR", "message": str(e)}}
            if code == "LIST_FAILED":
                return {"id": rid, "error": {"code": "LIST_FAILED", "message": str(e)}}
            msg_audio = str(e)
            if emit_fn:
                try:
                    emit_fn("logLine", {"line": f"error {msg_audio}"})
                    emit_fn("done", {"error": msg_audio})
                except Exception:
                    pass
            return {"id": rid, "error": {"code": "EXCEPTION", "message": msg_audio}}

    if method in ("getStore", "get_store", "getConfig"):
        try:
            data = load_store()
            return {"id": rid, "result": data}
        except Exception as e:
            return {"id": rid, "error": {"code": "EXCEPTION", "message": str(e)}}

    if method in ("setStore", "saveStore", "patchStore"):
        params = request.get("params") or {}
        if not isinstance(params, dict):
            return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "patch must be dict"}}
        try:
            import re as _re_store

            def _to_bool_store(v: Any) -> bool:
                if isinstance(v, bool):
                    return v
                if isinstance(v, str):
                    return v.strip().lower() in ("1", "true", "yes", "on")
                return bool(v)

            def _normalize_store_key(k: str) -> str:
                # canonical per DEFAULT_STORE: voice, rate, parallel, chunk-size, retries, scrapeDelay, safeMode, keepEPUB/MP3/M4B
                low = k.replace("-", "_").lower()
                # chunk variants
                if low in ("chunk_size", "chunksize"):
                    return "chunk-size"
                if low in ("scrape_delay", "scrapedelay"):
                    return "scrapeDelay"
                if low in ("safe_mode", "safemode"):
                    return "safeMode"
                if low in ("autoboilerplate", "auto_boilerplate", "auto-boilerplate"):
                    return "autoBoilerplate"
                if low in ("audiobitrate", "audio_bitrate", "audio-bitrate"):
                    return "audioBitrate"
                if low in ("keepepub", "keep_epub"):
                    return "keepEPUB"
                if low in ("keepmp3", "keep_mp3"):
                    return "keepMP3"
                if low in ("keepm4b", "keep_m4b"):
                    return "keepM4B"
                if low in ("outputdir", "output_dir", "output-dir"):
                    return "outputDir"
                if low in ("updateauto", "update_auto"):
                    return "updateAuto"
                if low in ("updateskipped", "update_skipped"):
                    return "updateSkipped"
                if low in ("locale", "language", "lang"):
                    return "locale"
                if low in ("engine", "tts_engine", "tts-engine"):
                    return "engine"
                if low in ("localvoice", "local_voice", "local-voice"):
                    return "localVoice"
                # direct canonicals keep case
                if k in ("chunk-size", "chunk_size", "chunkSize"):
                    return "chunk-size"
                if k in ("scrapeDelay", "scrape_delay", "scrape-delay"):
                    return "scrapeDelay"
                if k in ("safeMode", "safe_mode", "safe-mode"):
                    return "safeMode"
                if k in ("autoBoilerplate", "auto_boilerplate", "auto-boilerplate"):
                    return "autoBoilerplate"
                if k in ("audioBitrate", "audio_bitrate", "audio-bitrate"):
                    return "audioBitrate"
                if k in ("keepEPUB", "keepMP3", "keepM4B", "outputDir", "voice", "rate", "parallel", "retries", "filters", "scrapeDelay", "safeMode"):
                    return k
                # fallback: if lower matches known without case, map to canonical case
                # voice/rate etc lower is same
                if low in ("voice", "rate", "parallel", "retries", "filters"):
                    return low
                return k

            sanitized: Dict[str, Any] = {}
            for raw_k, v in params.items():
                if not isinstance(raw_k, str):
                    # non-string keys coerce to string? reject
                    return {"id": rid, "error": {"code": "VALUE_ERROR", "message": f"invalid key type {type(raw_k)}"}}
                ck = _normalize_store_key(raw_k)
                if ck == "voice":
                    if not isinstance(v, str):
                        return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "voice must be string"}}
                    vv = v.strip()
                    if not vv:
                        return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "voice must be non-empty"}}
                    if len(vv) > 100:
                        # clamp to 100 per AD-10 voice ≤100
                        vv = vv[:100]
                    sanitized[ck] = vv
                elif ck == "rate":
                    if not isinstance(v, str):
                        return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "rate must be string"}}
                    vv = v.strip()
                    if not _re_store.match(r"^[+-]?\d+%$", vv):
                        return {"id": rid, "error": {"code": "VALUE_ERROR", "message": f"invalid rate pattern {vv}"}}
                    try:
                        num = int(vv[:-1])
                    except Exception:
                        return {"id": rid, "error": {"code": "VALUE_ERROR", "message": f"invalid rate number {vv}"}}
                    num = max(-100, min(100, num))
                    sanitized[ck] = f"+{num}%" if num >= 0 else f"{num}%"
                elif ck == "engine":
                    if not isinstance(v, str):
                        return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "engine must be string"}}
                    vv = v.strip().lower()
                    if vv not in ("auto", "edge", "local"):
                        return {"id": rid, "error": {"code": "VALUE_ERROR", "message": f"invalid engine {vv}"}}
                    sanitized[ck] = vv
                elif ck == "localVoice":
                    if v is None:
                        sanitized[ck] = ""
                    elif isinstance(v, str):
                        vv = v.strip()
                        if not vv:
                            sanitized[ck] = ""
                        else:
                            try:
                                from core.tts_local import LOCAL_VOICES as _LOCAL_VOICES

                                if vv not in _LOCAL_VOICES:
                                    return {"id": rid, "error": {"code": "VALUE_ERROR", "message": f"unknown local voice {vv}"}}
                            except ImportError:
                                pass
                            sanitized[ck] = vv
                    else:
                        return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "localVoice must be string"}}
                elif ck == "parallel":
                    if isinstance(v, bool):
                        return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "parallel must be integer"}}
                    if isinstance(v, float):
                        return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "parallel must be integer"}}
                    try:
                        iv = int(v)  # type: ignore
                    except Exception:
                        return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "parallel must be integer"}}
                    iv = max(1, min(6, iv))
                    sanitized[ck] = iv
                elif ck == "chunk-size":
                    if isinstance(v, bool):
                        return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "chunk-size must be integer"}}
                    if isinstance(v, float):
                        return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "chunk-size must be integer"}}
                    try:
                        iv = int(v)  # type: ignore
                    except Exception:
                        return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "chunk-size must be integer"}}
                    iv = max(500, min(5000, iv))
                    sanitized[ck] = iv
                elif ck == "retries":
                    if isinstance(v, bool):
                        return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "retries must be integer"}}
                    if isinstance(v, float):
                        return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "retries must be integer"}}
                    try:
                        iv = int(v)  # type: ignore
                    except Exception:
                        return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "retries must be integer"}}
                    iv = max(1, min(10, iv))
                    sanitized[ck] = iv
                elif ck == "scrapeDelay":
                    if isinstance(v, bool):
                        return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "scrapeDelay must be integer"}}
                    if isinstance(v, float):
                        return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "scrapeDelay must be integer"}}
                    try:
                        iv = int(v)  # type: ignore
                    except Exception:
                        return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "scrapeDelay must be integer"}}
                    iv = max(0, min(20000, iv))
                    sanitized[ck] = iv
                elif ck == "safeMode":
                    sanitized[ck] = _to_bool_store(v)
                elif ck == "autoBoilerplate":
                    sanitized[ck] = _to_bool_store(v)
                elif ck == "audioBitrate":
                    if not isinstance(v, str):
                        return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "audioBitrate must be string"}}
                    vv = v.strip().lower()
                    import re as _re_br

                    m = _re_br.fullmatch(r"(\d+)\s*k", vv)
                    if not m or not (16 <= int(m.group(1)) <= 128):
                        return {"id": rid, "error": {"code": "VALUE_ERROR", "message": f"invalid audioBitrate {v}"}}
                    sanitized[ck] = f"{int(m.group(1))}k"
                elif ck in ("keepEPUB", "keepMP3", "keepM4B"):
                    sanitized[ck] = _to_bool_store(v)
                elif ck == "outputDir":
                    if not isinstance(v, str):
                        return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "outputDir must be string"}}
                    vv = v.strip()
                    if len(vv) > 260:
                        return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "outputDir too long"}}
                    if ".." in vv or "\0" in vv:
                        return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "outputDir invalid"}}
                    sanitized[ck] = vv
                elif ck == "updateAuto":
                    sanitized[ck] = _to_bool_store(v)
                elif ck == "updateSkipped":
                    if not isinstance(v, str):
                        return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "updateSkipped must be string"}}
                    sanitized[ck] = v.strip()[:64]
                elif ck == "locale":
                    if not isinstance(v, str):
                        return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "locale must be string"}}
                    vv = v.strip().lower()
                    if vv not in ("en", "pl", ""):
                        return {"id": rid, "error": {"code": "VALUE_ERROR", "message": f"invalid locale {v}"}}
                    sanitized[ck] = vv
                elif ck == "filters":
                    # keep filters as-is but validate basic shape to avoid corrupt store
                    if not isinstance(v, list):
                        return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "filters must be list"}}
                    sanitized[ck] = v
                else:
                    # unknown key — pass through verbatim under normalized key (preserve canonical if mapped, else raw)
                    sanitized[ck] = v
            saved = save_store(sanitized)
            return {"id": rid, "result": saved}
        except Exception as e:
            # preserve VALUE_ERROR code if already shaped
            if isinstance(e, TypeError) and "patch must be dict" in str(e):
                return {"id": rid, "error": {"code": "VALUE_ERROR", "message": str(e)}}
            return {"id": rid, "error": {"code": "EXCEPTION", "message": str(e)}}

    # For future methods, indicate mock only
    return {
        "id": rid,
        "error": {"code": "NOT_IMPLEMENTED", "message": "mock only — Epic 1.2 implements"},
    }


def _handle_list_chapters_count(rid: Any, url: str) -> Dict[str, Any]:
    """Validate URL, guess_adapter, return mock single row without aggregator."""
    import re
    from urllib.parse import urlparse

    # Basic URL validation ^https?://
    if not re.match(r"^https?://", url, re.I):
        return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "url must be http(s)"}}
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        if not host:
            return {"id": rid, "error": {"code": "VALUE_ERROR", "message": "url must contain host"}}
    except Exception as e:
        return {"id": rid, "error": {"code": "VALUE_ERROR", "message": str(e)}}

    # Guess adapter host-suffix (dynamic import to keep importlinter happy)
    site = "—"
    guess: Any = None
    try:
        import importlib

        _mod = importlib.import_module("adapters.base")
        guess_adapter = getattr(_mod, "guess_adapter")
        guess = guess_adapter(url)
        if guess == "novelphoenix":
            site = "novelphoenix.com"
        elif guess is not None:
            site = str(guess)
        else:
            # if host itself is novelphoenix, treat as known even if guess missed — exact suffix check prevents spoof
            if host == "novelphoenix.com" or host.endswith(".novelphoenix.com"):
                site = "novelphoenix.com"
                guess = "novelphoenix"
            else:
                # show host as site, not block
                site = host or "—"
    except Exception:
        site = host or "—"

    # Mock single row without network (listChaptersCount would require fetch;
    # for spec 1.3 mock is sufficient, no aggregator call)
    title = url  # could be derived, but keep url as title for mock
    # Provide readable title from last path segment if available
    try:
        last = parsed.path.rstrip("/").split("/")[-1]
        if last and len(last) >= 2:
            # decode dash?
            title = last.replace("-", " ")
    except Exception:
        pass

    result = [
        {
            "site": site,
            "title": title,
            "url": url,
            "link": url,
            "chapters": None,
            "chapter_count": None,
            "author": None,
            "cover_url": None,
        }
    ]
    return {"id": rid, "result": result}


def run_sidecar_loop() -> None:
    """Run JSON-RPC loop over stdin/stdout (line-delimited JSON)."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        if len(line) > 1_000_000:
            resp = {"id": "0", "error": {"code": "TOO_LARGE", "message": "line exceeds 1MB"}}
            try:
                sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
                sys.stdout.flush()
            except BrokenPipeError:
                break
            continue
        try:
            req = json.loads(line)
            # preserve id for error correlation even if req is not dict
            rid = req.get("id", "0") if isinstance(req, dict) else "0"

            # streaming emit shim: handle_rpc can emit events before final response
            def _emit(event: str, payload: Any):
                try:
                    sys.stdout.write(json.dumps({"event": event, "payload": payload}, ensure_ascii=False) + "\n")
                    sys.stdout.flush()
                except BrokenPipeError:
                    pass
                except Exception:
                    pass

            resp = handle_rpc(req, emit_fn=_emit)
            # ensure response id matches request when handle_rpc returns BAD_REQUEST with 0
            if isinstance(req, dict) and "id" in req and resp.get("id") == "0" and rid != "0":
                resp["id"] = rid
        except Exception as e:
            # try to extract id from raw JSON for correlation
            try:
                raw = json.loads(line)
                rid2 = raw.get("id", "0") if isinstance(raw, dict) else "0"
            except Exception:
                rid2 = "0"
            resp = {"id": rid2, "error": {"code": "EXCEPTION", "message": str(e)}}
        try:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
        except BrokenPipeError:
            break


if __name__ == "__main__":
    # Allow `python -m core.config` or `python core/config.py` to run loop
    # Add repo root to path when executed directly
    run_sidecar_loop()
