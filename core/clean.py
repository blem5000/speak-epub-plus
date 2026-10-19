"""
core/clean.py — Content boundary selector isolation + heuristic fallback (Story 2.2).
AD-7: per-adapter Selectors source of truth, heuristic only fallback never overwrites adapter.
AD-2: raw never filtered, clean is Pipes filter raw -> (html,text) fed to preview/epub.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Tuple

from bs4 import BeautifulSoup

from core.ports import Selectors

# Chrome that is never book content for novels: scripts/styles/nav plus
# interactive/ad containers. <select> is the chapter-jump dropdown, <button>
# the reader settings gear, <iframe>/<object>/<embed>/<canvas> ad slots or
# trackers (they render as grey boxes offline), form controls likewise.
# prev/next <a rel> links are handled separately (attribute selector).
_NOISE_TAGS = [
    "script",
    "style",
    "nav",
    "aside",
    "iframe",
    "select",
    "button",
    "form",
    "input",
    "textarea",
    "object",
    "embed",
    "canvas",
    "dialog",
    # site chrome that is not book content
    "header",
    "footer",
    "figure",
    "figcaption",
    "svg",
    "video",
    "audio",
    "picture",
]

# Unambiguous navigation links (prev/next chapter). Practically never story.
# the "i" flag makes the attribute value match case-insensitively (rel="Next")
_NAV_LINK_SELECTORS = ["a[rel='prev' i]", "a[rel='next' i]", "a[rel='previous' i]"]

# Heuristic fallback order — matches adapters/novelphoenix.py fallback + ARCHITECTURE-SPINE AD-7
_HEURISTIC_SELECTORS = [
    "article",
    "#content",
    ".chapter-content",
    "#chapter-content",
    ".content",
    "#chapters",
]

# Legacy location (inside the package tree) — kept only as a fallback for
# installations that already have overrides there.
_OVERRIDES_DIR: Path = Path(__file__).resolve().parents[1] / "adapters" / "overrides"


def _site_for_adapter(adapter) -> str:
    """Derive site key from adapter instance. Fallback to novelphoenix.com for known adapter."""
    try:
        name = adapter.__class__.__name__ if adapter is not None else ""
        if "NovelPhoenix" in name:
            return "novelphoenix.com"
        # try BASE attr if exists
        base = getattr(adapter, "BASE", None)
        if isinstance(base, str) and base.strip():
            from urllib.parse import urlparse

            host = urlparse(base).hostname or ""
            if host:
                return host.lower().rstrip(".")
        # generic: lower class name without adapter suffix
        if name:
            return name.lower().replace("adapter", "").strip() or "generic"
    except Exception:
        pass
    return "novelphoenix.com"


def _overrides_path(site: str) -> Path:
    safe = site.lower().strip().rstrip(".") or "generic"
    if safe.startswith("www."):
        safe = safe[4:]
    # sanitize: allow only alnum, dot, dash; replace others (including colon, *, ?, ..)
    import re as _re

    safe = _re.sub(r"[^a-z0-9.\-]", "_", safe)
    safe = safe.replace("..", "_")
    safe = safe.strip("._") or "generic"
    # Windows reserved device names (CON, NUL, COM1...) cannot be a filename
    if safe.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", "COM1", "LPT1"}:
        safe = "_" + safe
    return _overrides_dir() / f"{safe}.json"


def _overrides_dir() -> Path:
    """Directory holding the user's selector overrides.

    It must live in the USER data area, not inside the package tree: the
    installed app writes into Program Files (read-only) and loses the
    overrides on every update.
    """
    override = os.environ.get("SPEAK_EPUB_OVERRIDES_DIR")
    if override:
        return Path(override)
    if os.name == "nt":
        base = os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")
        return Path(base) / "speak-epub" / "overrides"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "speak-epub" / "overrides"
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "speak-epub" / "overrides"


def _legacy_overrides_path(site: str) -> Path:
    """Old location (inside the package tree) — read-only fallback."""
    safe = site.lower().strip().rstrip(".") or "generic"
    if safe.startswith("www."):
        safe = safe[4:]
    safe = re.sub(r"[^a-z0-9.\-]", "_", safe).replace("..", "_").strip("._") or "generic"
    if safe.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", "COM1", "LPT1"}:
        safe = "_" + safe
    return _OVERRIDES_DIR / f"{safe}.json"


def load_overrides(site: str) -> Selectors | None:
    p = _overrides_path(site)
    if not p.is_file():
        # an override saved by an older version lives in the package tree
        legacy = _legacy_overrides_path(site)
        if legacy.is_file():
            p = legacy
        else:
            return None
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError:
        # a transient read failure (file locked, sharing violation) must NOT
        # destroy the user's settings — just skip the override for now
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        # really corrupted content -> drop it
        try:
            p.unlink()
        except OSError:
            pass
        return None
    if not isinstance(data, dict):
        try:
            p.unlink()
        except OSError:
            pass
        return None
    start = data.get("start")
    end = data.get("end")
    # validate types: allow None or non-empty str
    if start is not None and not isinstance(start, str):
        return None
    if end is not None and not isinstance(end, str):
        return None
    if isinstance(start, str) and not start.strip():
        start = None
    if isinstance(end, str) and not end.strip():
        end = None
    return Selectors(start=start, end=end)


def save_overrides(site: str, selectors: Selectors) -> Path:
    p = _overrides_path(site)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"start": selectors.start, "end": selectors.end}
    # a per-process temp name: two concurrent saves must not share a file
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(p)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
    return p


def clear_overrides(site: str) -> bool:
    p = _overrides_path(site)
    try:
        if p.is_file():
            p.unlink()
            return True
    except Exception:
        pass
    return False


def resolve_selectors(adapter) -> Selectors:
    """Return effective Selectors: override if exists else adapter.getSelectors()."""
    try:
        default = adapter.getSelectors() if adapter is not None else Selectors(start="div#chapter-content", end=None)
    except Exception:
        default = Selectors(start="div#chapter-content", end=None)
    site = _site_for_adapter(adapter)
    ov = load_overrides(site)
    if ov is not None:
        # Per-field merge: an override that only sets `end` must NOT discard
        # the adapter's default `start` (that silently emptied the chapter
        # and pushed the extraction into the heuristic path).
        return Selectors(
            start=ov.start if ov.start is not None else default.start,
            end=ov.end if ov.end is not None else default.end,
        )
    return default


def _strip_noise(tag) -> None:
    for t in tag(_NOISE_TAGS):
        t.decompose()
    for sel in _NAV_LINK_SELECTORS:
        try:
            for el in tag.select(sel):
                el.decompose()
        except Exception:
            continue
    # Linked headings are site chrome (linked novel title / chapter dropdown
    # label), never the story title — drop them so they can't leak into the
    # chapter head or the title fallback chain.
    try:
        for h in tag.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
            try:
                if h.find(["a", "button", "select", "input"]):
                    h.decompose()
            except Exception:
                continue
    except Exception:
        pass


def _text_of(tag) -> str:
    txt = tag.get_text(separator=" ", strip=True)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt


def clean_html(raw_html: str, start: str | None, end: str | None, on_log=None) -> Tuple[str, str]:
    """
    Isolate chapter body via selectors.

    - start: CSS selector source of truth. If None/empty, skip to heuristic.
    - end: optional end boundary, sibling walk start..end exclusive.
    - heuristic: tried only if start select misses or yields empty text.
    - invalid CSS raises ValueError("invalid selector: ...").
    - on_log: optional callback telling WHICH path produced the text (the
      whole-page fallback is otherwise indistinguishable from a real chapter)

    Returns (html, text) — html is outerHTML of isolated fragment, text normalized.
    Fallback body if all miss. Never raises for empty isolation, returns ("","")? Actually returns body html/text even if empty.
    """
    raw = raw_html or ""
    soup = BeautifulSoup(raw, "lxml")

    # try start selector
    target = None
    if start:
        s = start.strip()
        if s:
            try:
                target = soup.select_one(s)
            except Exception as e:
                raise ValueError(f"invalid selector: {s} {e}") from e
            if target is not None:
                # strip noise
                _strip_noise(target)
                # handle end boundary if present
                if end:
                    e_sel = end.strip()
                    if e_sel:
                        try:
                            end_el = soup.select_one(e_sel)
                        except Exception as ee:
                            raise ValueError(f"invalid selector: {e_sel} {ee}") from ee
                        if end_el is not None and end_el is not target:
                            # sibling walk: collect target + following siblings until end_el
                            # Determine if end_el is after target in document order
                            # Use find_next to check order
                            try:
                                # if end_el is descendant of target, truncate target before end_el
                                if end_el in target.descendants:
                                    # remove end_el and following siblings inside target
                                    # simpler: decompose end_el subtree
                                    end_el.decompose()
                                else:
                                    # Check if end_el comes after target via find_next
                                    # Walk siblings of target
                                    # If end_el is sibling or later sibling at same parent level, collect
                                    # Detect by checking parent
                                    # Use find_next_siblings of target
                                    collected = [str(target)]
                                    # Collect following siblings until hitting end_el
                                    hit_end = False
                                    for sib in list(target.find_next_siblings()):
                                        if sib == end_el:
                                            hit_end = True
                                            break
                                        # if sib contains end_el, break before sib
                                        try:
                                            if hasattr(sib, "descendants") and end_el in sib.descendants:
                                                hit_end = True
                                                break
                                        except Exception:
                                            pass
                                        # if sib matches end selector directly, break
                                        try:
                                            if sib.select_one(e_sel) is end_el:
                                                hit_end = True
                                                break
                                        except Exception:
                                            pass
                                        collected.append(str(sib))
                                    # the end boundary was never reached: the walk
                                    # would return the WHOLE remaining tail of
                                    # the page as "chapter" content
                                    if hit_end and len(collected) > 1:
                                        # Re-parse collected to normalize
                                        combined = "".join(collected)
                                        c_soup = BeautifulSoup(combined, "lxml")
                                        for t in c_soup(_NOISE_TAGS):
                                            t.decompose()
                                        # html is combined outer
                                        html = "".join(str(c) for c in c_soup.body.contents) if c_soup.body else combined
                                        text = c_soup.get_text(separator=" ", strip=True)
                                        text = re.sub(r"\s+", " ", text).strip()
                                        if text:
                                            return html, text
                                        # if text empty after end walk, fall through to target-only?
                            except Exception:
                                pass
                html = str(target)
                text = _text_of(target)
                if text:
                    return html, text
                # empty text -> fall through to heuristic
                target = None

    if target is None:
        # heuristic fallback
        heuristic = None
        for sel in _HEURISTIC_SELECTORS:
            try:
                heuristic = soup.select_one(sel)
                if heuristic is not None:
                    break
            except Exception:
                continue
        if heuristic is not None:
            _strip_noise(heuristic)
            # the end boundary applies to the heuristic path too (it used to
            # be ignored here, so the extraction ran past the intended end)
            if end and end.strip():
                try:
                    end_el = soup.select_one(end.strip())
                except Exception as ee:
                    raise ValueError(f"invalid selector: {end.strip()} {ee}") from ee
                if end_el is not None:
                    try:
                        if end_el in heuristic.descendants:
                            # remove the end marker AND everything after it
                            # (decomposing the marker alone left the trailing
                            # content in place)
                            for sib in list(end_el.find_next_siblings()):
                                try:
                                    sib.decompose()
                                except Exception:
                                    pass
                            end_el.decompose()
                    except Exception:
                        pass
            html = str(heuristic)
            text = _text_of(heuristic)
            if text:
                if on_log is not None:
                    try:
                        on_log("chapter extraction: heuristic selector")
                    except Exception:
                        pass
                return html, text
        # fallback body
        # need fresh soup without decomposed target? We already decomposed noise from soup parts, but re-strip all
        for tag in soup(_NOISE_TAGS):
            tag.decompose()
        for sel in _NAV_LINK_SELECTORS:
            try:
                for el in soup.select(sel):
                    el.decompose()
            except Exception:
                continue
        body = soup.body or soup
        html = str(body)
        text = body.get_text(separator=" ", strip=True)
        text = re.sub(r"\s+", " ", text).strip()
        if on_log is not None:
            try:
                # the whole page is the fallback: the user must know that the
                # site markup probably changed
                on_log("chapter extraction: WHOLE PAGE fallback (selectors missed)")
            except Exception:
                pass
        return html, text

    # should not reach
    return "", ""
