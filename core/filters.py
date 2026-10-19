"""
core/filters.py — Filter gate for plain + regex line removal (Story 2.3)
+ automatic boilerplate detection (recurring head/tail lines across chapters).
AD-2: raw never filtered, filter applies once after clean_html on cleaned text.
Pure module — no adapter imports, keeps GUI→Core→Port→Adapter.
"""
from __future__ import annotations

import re
from typing import Any, List, Tuple

Filter = dict[str, Any]  # {pattern:str, isRegex:bool} canonical

# Boilerplate detection tuning — see detect_boilerplate docstring.
_BOILERPLATE_MIN_CHAPTERS = 2
_BOILERPLATE_HEAD_LINES = 15
_BOILERPLATE_TAIL_LINES = 15
_BOILERPLATE_MIN_LEN = 3
_BOILERPLATE_MAX_TEMPLATES = 200
_BOILERPLATE_MAX_LINE_LEN = 200


def mask_numbers(line: str) -> str:
    """Replace digit runs with # so 'Chapter 57' matches 'Chapter 58'."""
    return re.sub(r"\d+", "#", line)


_BLOCK_TAGS = ("p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "pre", "a")
# Structural tags only (links are inline — a div with just links is still a leaf line)
_STRUCTURAL_TAGS = ("p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "pre")


def html_to_block_lines(html: str) -> List[str]:
    """Split cleaned HTML into block texts in document order (true lines).

    clean_html joins everything with spaces, so plain splitlines() would see
    one giant line. Block elements (p/headings/items + leaf div containers)
    are the real lines for boilerplate detection. Standalone links (<a>
    report/share buttons whose text never appears as a block) are included
    too — story links are unique per chapter and never match a template.
    """
    if not html or not isinstance(html, str) or not html.strip():
        return []
    try:
        from bs4 import BeautifulSoup
    except Exception:
        return [ln.strip() for ln in html.splitlines() if ln.strip()]
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        return [ln.strip() for ln in html.splitlines() if ln.strip()]
    body = soup.body if soup.body else soup
    lines: List[str] = []
    for el in body.find_all(list(_BLOCK_TAGS) + ["div", "section", "article", "li", "blockquote", "a"]):
        try:
            if el.name in ("div", "section", "article") and el.find(list(_STRUCTURAL_TAGS)):
                continue  # container — children carry the lines
            # a nested block/link inside another block would repeat its
            # parent's text ("Report Share" + "Report" + "Share") — the
            # duplicate was spoken twice
            if el.name in ("li", "blockquote", "a") and el.find_parent(
                list(_BLOCK_TAGS) + ["div", "section", "article", "li", "blockquote"]
            ):
                continue
            txt = el.get_text(separator=" ", strip=True)
            txt = re.sub(r"\s+", " ", txt).strip()
            if txt:
                lines.append(txt)
        except Exception:
            continue
    return lines


def _template_regex(line: str) -> str:
    """Whole-line regex for a detected template: literals escaped, digit runs wild."""
    parts = re.split(r"(\d+)", line)
    rx = "".join(r"\d+" if p.isdigit() else re.escape(p) for p in parts)
    return f"^{rx}$"


def detect_boilerplate(
    texts: List[str],
    min_chapters: int = _BOILERPLATE_MIN_CHAPTERS,
    head_lines: int = _BOILERPLATE_HEAD_LINES,
    tail_lines: int = _BOILERPLATE_TAIL_LINES,
) -> List[Filter]:
    """Find recurring header/footer lines across chapters (user: auto-filter junk).

    Only lines in the head/tail zones (first/last N lines) of each chapter can
    become templates, and only templates seen in >= min_chapters chapters are
    kept. Digit runs are masked, so 'Chapter 57'/'Chapter 58' collapse while a
    distinctive title like 'Chapter 57: She Has Arrived' stays unique.

    Safety is positional + anchored: templates are LEARNED only from edges,
    and removal matches whole lines (^...$), so a story sentence merely
    CONTAINING template text is never touched. A mid-chapter line identical
    to an edge template is still removed — accepted (indistinguishable from
    injected ads, and vanishingly rare for anchored matches); disable with
    the autoBoilerplate store toggle if ever unwanted.

    `texts` is a list of chapters, each either a "\n"-separated string or a
    pre-split list of block lines (see html_to_block_lines — REQUIRED for
    clean_html output, which joins everything with spaces).

    Returns canonical regex filters with source:"auto" (transient — never
    persisted to store.json), most-widespread first.
    """
    if not texts or not isinstance(texts, list):
        return []
    per_chapter: List[List[str]] = []
    for text in texts:
        if isinstance(text, (list, tuple)):
            lines = [ln.strip() for ln in text if isinstance(ln, str) and ln.strip()]
        elif isinstance(text, str) and text:
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        else:
            continue
        if lines:
            per_chapter.append(lines)
    if not per_chapter:
        return []
    votes: dict[str, set[int]] = {}
    samples: dict[str, str] = {}
    for ch_idx, lines in enumerate(per_chapter):
        n = len(lines)
        seen_in_chapter: set[str] = set()
        # the head and tail zones must not overlap: for a short chapter their
        # union covered the WHOLE chapter, so every line of it could become
        # a removal template. The zones are now capped so that at least one
        # middle line always stays protected.
        _k = max(1, min(max(head_lines, 0), max(tail_lines, 0), max(0, (n - 1) // 2)))
        for i, line in enumerate(lines):
            if len(line) < _BOILERPLATE_MIN_LEN or len(line) > _BOILERPLATE_MAX_LINE_LEN:
                continue
            in_head = i < _k
            in_tail = i >= n - _k
            if not (in_head or in_tail):
                continue
            template = mask_numbers(line)
            if len(template) < _BOILERPLATE_MIN_LEN:
                continue
            if template in seen_in_chapter:
                continue
            seen_in_chapter.add(template)
            votes.setdefault(template, set()).add(ch_idx)
            samples.setdefault(template, line)
    if min_chapters < 2:
        min_chapters = 2
    out: List[Filter] = []
    ranked = sorted(votes.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    for template, chapters in ranked:
        if len(chapters) < min_chapters:
            continue
        try:
            pattern = _template_regex(samples.get(template, template))
            re.compile(pattern)
        except re.error:
            continue
        out.append({"pattern": pattern, "isRegex": True, "source": "auto", "chapters": len(chapters)})
        if len(out) >= _BOILERPLATE_MAX_TEMPLATES:
            break
    return out


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
        # bs4 is missing — fall back to plain text filtering (calling
        # BeautifulSoup here would only raise a NameError)
        txt = "\n".join(ln.strip() for ln in html.splitlines() if ln.strip())
        filtered, removed = apply_filters(txt, deduped)
        return html, removed
    soup = BeautifulSoup(html, "lxml")
    # Find candidate blocks: p, div, h1-h6, li, blockquote, pre
    # If html is fragment without body, use soup itself
    body = soup.body if soup.body else soup
    # Collect all block elements; exclude outer container (div#chapter-content) to avoid deleting whole chapter
    # Standalone links are candidates too (report/share buttons whose text is
    # not a block); story links never match an anchored boilerplate template.
    candidates_all = body.find_all(["p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "section", "article", "a"])
    # protected containers: a wrapper that HOLDS the chapter content must
    # never be removed as a whole, whatever its id/class
    def _is_content_container(el) -> bool:
        if el.name != "div":
            return False
        if el.get("id") == "chapter-content":
            return True
        if el.find(["p"]) is not None:
            return True
        # a wrapper whose whole subtree is block-level content
        return el.find(["p", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote"]) is not None

    candidates = [el for el in candidates_all if not _is_content_container(el)]
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
        # Links are inline: only remove a link when its ENTIRE text matches
        # (report/share buttons), never for a substring hit that would eat
        # linked story words a manual plain filter happens to contain.
        link_only = el.name == "a"
        hit = False
        for pat, is_regex, rx in compiled:
            if is_regex:
                m = rx.search(el_text)  # type: ignore
                if m and (not link_only or (m.group(0) == el_text)):
                    hit = True
                    break
            else:
                if link_only:
                    if pat == el_text:
                        hit = True
                        break
                elif pat in el_text:
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
        # the SAME canonicalization as _normalize_filter: a filter written as
        # {"type": "regex"} or {"isRegex": "1"} must behave identically on
        # every path (it used to be a PLAIN substring filter here)
        is_regex = f.get("isRegex", f.get("is_regex", f.get("type") == "regex"))
        if isinstance(is_regex, str):
            is_regex = is_regex.lower() in ("regex", "true", "1")
        is_regex = bool(is_regex) if is_regex is not None else False
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
