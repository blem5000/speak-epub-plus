"""
core/filters.py — Filter gate for plain + regex line removal (Story 2.3).
AD-2: raw never filtered, filter applies once after clean_html on cleaned text.
Pure module — no adapter imports, keeps GUI→Core→Port→Adapter.
"""
from __future__ import annotations

import re
from typing import Any, List, Tuple

Filter = dict[str, Any]  # {pattern:str, isRegex:bool} canonical


def _normalize_filter(f: Any) -> Tuple[str, bool]:
    if not isinstance(f, dict):
        raise ValueError("filter must be object")
    pat = f.get("pattern", f.get("phrase", f.get("text")))
    is_regex = f.get("isRegex", f.get("is_regex", f.get("type") == "regex"))
    # coerce isRegex when type badge provided
    if isinstance(is_regex, str):
        is_regex = is_regex.lower() in ("regex", "true", "1")
    is_regex = bool(is_regex) if is_regex is not None else False
    if not isinstance(pat, str):
        raise ValueError("filter pattern must be string")
    pat = pat.strip()
    if not pat:
        raise ValueError("filter pattern must be non-empty")
    if len(pat) > 200:
        raise ValueError("filter pattern too long (max 200)")
    return pat, is_regex


def _compile_filters(filters: List[Filter]):
    compiled = []
    for f in filters:
        pat, is_regex = _normalize_filter(f)
        if is_regex:
            try:
                rx = re.compile(pat)
            except re.error as e:
                raise ValueError(f"invalid regex: {pat} {e}") from e
            compiled.append((pat, True, rx))
        else:
            compiled.append((pat, False, None))
    return compiled


def _dedup(filters: List[Filter]) -> List[Filter]:
    seen: set[str] = set()
    out: List[Filter] = []
    for f in filters:
        try:
            pat, is_regex = _normalize_filter(f)
        except ValueError:
            continue
        key = f"{pat}|{is_regex}"
        if key in seen:
            continue
        seen.add(key)
        out.append({"pattern": pat, "isRegex": is_regex})
    return out


def apply_filters(cleaned_text: str, filters: List[Filter] | None) -> Tuple[str, int]:
    """
    Apply plain + regex line filter once.

    - plain:  `pattern in line` case-sensitive
    - regex:  `re.search(pattern, line)` case-sensitive unless inline (?i)
    - line-wise: splitlines(), remove whole line if any filter matches, preserve order, join with "\n"
    - compiled once per call, idempotent

    Returns (filtered_text, removed_count)
    """
    if not filters:
        return cleaned_text or "", 0
    if not isinstance(filters, list):
        raise ValueError("filters must be list")
    # dedup and validate + compile once
    deduped = _dedup(filters)
    # re-validate deduped via compile (also catches invalid regex)
    compiled = _compile_filters(deduped)
    if not compiled:
        return cleaned_text or "", 0
    text = cleaned_text or ""
    lines = text.splitlines()
    # empty text -> no lines
    if not lines and text == "":
        return "", 0
    kept: List[str] = []
    removed = 0
    for line in lines:
        hit = False
        for pat, is_regex, rx in compiled:
            if is_regex:
                # type: ignore
                if rx.search(line):  # type: ignore
                    hit = True
                    break
            else:
                if pat in line:
                    hit = True
                    break
        if hit:
            removed += 1
        else:
            kept.append(line)
    # preserve trailing newline style: join with \n, no extra trailing \n unless original had it?
    # Use simple join; tests expect splitlines() semantics
    filtered = "\n".join(kept)
    return filtered, removed


def apply_filters_to_html(cleaned_html: str, filters: List[Filter] | None) -> Tuple[str, int]:
    """
    Apply filters to HTML by removing block elements whose text matches.
    Parses cleaned_html, removes <p>, <div>, <h*> etc. whose inner text contains pattern.
    Returns (filtered_html, removed_count).
    """
    if not filters:
        return cleaned_html or "", 0
    if not isinstance(filters, list):
        raise ValueError("filters must be list")
    deduped = _dedup(filters)
    compiled = _compile_filters(deduped)
    if not compiled:
        return cleaned_html or "", 0
    html = cleaned_html or ""
    if not html.strip():
        return html, 0
    try:
        from bs4 import BeautifulSoup
    except Exception:
        # fallback to text filtering
        txt = BeautifulSoup(html, "lxml").get_text(separator="\n", strip=True) if html else ""
        filtered, removed = apply_filters(txt, deduped)
        return html, removed
    soup = BeautifulSoup(html, "lxml")
    # Find candidate blocks: p, div, h1-h6, li, blockquote, pre
    # If html is fragment without body, use soup itself
    body = soup.body if soup.body else soup
    # Collect all block elements; exclude outer container (div#chapter-content) to avoid deleting whole chapter
    candidates_all = body.find_all(["p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "section", "article"])
    candidates = [el for el in candidates_all if not (el.name == "div" and el.get("id") == "chapter-content")]
    # also exclude wrapper divs that contain multiple block children (avoid nuking chapter when inner p matches)
    # If a div contains at least one p descendant, treat it as container not leaf — skip it
    filtered_candidates = []
    for el in candidates:
        if el.name == "div" and el.find("p"):
            continue
        filtered_candidates.append(el)
    candidates = filtered_candidates
    if not candidates:
        # fallback: treat html as text
        text = body.get_text(separator="\n", strip=True)
        filtered_text, removed = apply_filters(text, deduped)
        if removed:
            # if we removed via text, reflect removal in html by returning filtered_text wrapped?
            # keep original html but indicate removed
            return html, removed
        return html, 0
    removed = 0
    for el in list(candidates):
        # get text for this element
        el_text = el.get_text(separator=" ", strip=True)
        el_text = re.sub(r"\s+", " ", el_text).strip()
        hit = False
        for pat, is_regex, rx in compiled:
            if is_regex:
                if rx.search(el_text):  # type: ignore
                    hit = True
                    break
            else:
                if pat in el_text:
                    hit = True
                    break
        if hit:
            el.decompose()
            removed += 1
    # Re-serialize
    if soup.body:
        filtered_html = "".join(str(c) for c in soup.body.contents) if soup.body.contents else ""
    else:
        filtered_html = str(soup)
    if not filtered_html.strip():
        # if all removed, keep empty
        filtered_html = ""
    return filtered_html, removed


def sanitize_filters(raw: Any) -> List[Filter]:
    """Sanitize raw filters[] from store.json to canonical list."""
    if not isinstance(raw, list):
        return []
    out: List[Filter] = []
    seen: set[str] = set()
    for f in raw:
        if not isinstance(f, dict):
            continue
        pat = f.get("pattern", f.get("phrase", f.get("text")))
        is_regex = f.get("isRegex", f.get("is_regex", False))
        if isinstance(is_regex, str):
            is_regex = is_regex.lower() == "regex" or is_regex.lower() == "true"
        if not isinstance(pat, str):
            continue
        pat = pat.strip()
        if not pat or len(pat) > 200:
            continue
        # validate regex compiles if isRegex
        if is_regex:
            try:
                re.compile(pat)
            except re.error:
                # keep invalid? skip for sanitize, but addFilter will reject
                continue
        key = f"{pat}|{bool(is_regex)}"
        if key in seen:
            continue
        seen.add(key)
        out.append({"pattern": pat, "isRegex": bool(is_regex)})
    return out
