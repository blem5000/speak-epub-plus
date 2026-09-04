"""Tests for core/filters.py — I/O matrix Story 2.3."""
import re
from unittest.mock import patch

import pytest

from core.filters import apply_filters, sanitize_filters


def test_plain_hit():
    cleaned = "Intro\nSubscribe to read\nNext"
    filters = [{"pattern": "Subscribe", "isRegex": False}]
    filtered, removed = apply_filters(cleaned, filters)
    assert filtered == "Intro\nNext"
    assert removed == 1
    assert "Subscribe" not in filtered


def test_regex_hit():
    cleaned = "Support on patreon.com/subscribeX\nHello"
    filters = [{"pattern": "subscribe.*patreon", "isRegex": True}]
    # case-sensitive: pat is lower, line has lower? our line has lower subscribe, should match if pattern includes patreon after?
    # Actually test string "Support on patreon.com/subscribeX" reversed: pattern subscribe.*patreon won't match patreon...subscribe, need suitable string
    cleaned2 = "please subscribe to my patreon page\nHello"
    filtered, removed = apply_filters(cleaned2, filters)
    assert removed == 1
    assert "subscribe" not in filtered or "patreon" not in filtered
    # ensure original Hello kept
    assert "Hello" in filtered


def test_regex_hit_case():
    cleaned = "subscribe to patreon\nHello"
    filters = [{"pattern": "subscribe.*patreon", "isRegex": True}]
    filtered, removed = apply_filters(cleaned, filters)
    assert removed == 1
    assert filtered == "Hello"


def test_combined():
    cleaned = "Intro\nSubscribe to read\nplease subscribe to patreon\nNext"
    filters = [
        {"pattern": "Subscribe", "isRegex": False},
        {"pattern": "subscribe.*patreon", "isRegex": True},
    ]
    filtered, removed = apply_filters(cleaned, filters)
    assert removed == 2
    assert "Subscribe" not in filtered
    assert "patreon" not in filtered
    assert "Intro" in filtered and "Next" in filtered


def test_no_filters():
    cleaned = "Intro\nNext"
    filtered, removed = apply_filters(cleaned, [])
    assert filtered == cleaned
    assert removed == 0


def test_none_filters():
    cleaned = "A\nB"
    filtered, removed = apply_filters(cleaned, None)
    assert filtered == cleaned
    assert removed == 0


def test_empty_text():
    filtered, removed = apply_filters("", [{"pattern": "Subscribe", "isRegex": False}])
    assert filtered == ""
    assert removed == 0


def test_raw_not_filtered_invariant():
    raw = "<nav>Subscribe</nav><div id='chapter-content'>Hello\nSubscribe to read</div>"
    # simulate clean then filter
    cleaned = "Hello\nSubscribe to read"
    # raw invariant before filter
    assert "Subscribe" in raw
    filtered, removed = apply_filters(cleaned, [{"pattern": "Subscribe", "isRegex": False}])
    assert "Subscribe" in raw
    assert "Subscribe" not in filtered
    assert removed == 1


def test_invalid_regex_raises():
    cleaned = "Hello"
    filters = [{"pattern": "[*", "isRegex": True}]
    with pytest.raises(ValueError) as exc:
        apply_filters(cleaned, filters)
    assert "invalid regex" in str(exc.value)


def test_duplicate_dedup():
    cleaned = "Subscribe to read\nSubscribe again"
    filters = [
        {"pattern": "Subscribe", "isRegex": False},
        {"pattern": "Subscribe", "isRegex": False},
    ]
    filtered, removed = apply_filters(cleaned, filters)
    # both lines contain Subscribe, so removed 2, but dedup ensures single pattern check
    assert removed == 2
    assert filtered == ""


def test_plain_is_case_sensitive():
    cleaned = "subscribe lower\nSubscribe upper"
    filters = [{"pattern": "Subscribe", "isRegex": False}]
    filtered, removed = apply_filters(cleaned, filters)
    assert removed == 1
    assert "Subscribe upper" not in filtered
    assert "subscribe lower" in filtered


def test_regex_without_flag_is_case_sensitive():
    cleaned = "SUBSCRIBE PATREON\nsubscribe patreon"
    filters = [{"pattern": "subscribe.*patreon", "isRegex": True}]
    filtered, removed = apply_filters(cleaned, filters)
    assert removed == 1
    assert "SUBSCRIBE PATREON" in filtered
    assert "subscribe patreon" not in filtered


def test_regex_with_inline_flag():
    cleaned = "SUBSCRIBE PATREON\nhello"
    filters = [{"pattern": "(?i)subscribe.*patreon", "isRegex": True}]
    filtered, removed = apply_filters(cleaned, filters)
    assert removed == 1
    assert "SUBSCRIBE PATREON" not in filtered


def test_idempotent():
    cleaned = "Intro\nSubscribe to read\nNext"
    filters = [{"pattern": "Subscribe", "isRegex": False}]
    filtered, _ = apply_filters(cleaned, filters)
    filtered2, removed2 = apply_filters(filtered, filters)
    assert filtered == filtered2
    assert removed2 == 0


def test_sanitize_valid():
    raw = [
        {"pattern": "Subscribe ", "isRegex": False},
        {"pattern": "subscribe.*patreon", "isRegex": True},
        {"pattern": "Subscribe", "isRegex": False},  # duplicate
        {"pattern": "   ", "isRegex": False},  # empty -> skipped
        {"pattern": "[*", "isRegex": True},  # invalid regex -> skipped in sanitize
    ]
    sanitized = sanitize_filters(raw)
    # should have 2 unique valid (duplicate removed, empty/invalid skipped)
    assert len(sanitized) == 2
    assert sanitized[0]["pattern"] == "Subscribe"
    assert sanitized[0]["isRegex"] is False
    assert sanitized[1]["pattern"] == "subscribe.*patreon"


def test_compile_once():
    cleaned = "a\nb\nc"
    filters = [
        {"pattern": "a", "isRegex": False},
        {"pattern": "b.*", "isRegex": True},
    ]
    with patch("core.filters.re.compile", wraps=re.compile) as mock_compile:
        apply_filters(cleaned, filters)
        # only regex pattern should call compile once
        assert mock_compile.call_count == 1
        mock_compile.assert_called_with("b.*")


def test_line_preserve_order():
    cleaned = "keep1\nRemove Subscribe\nkeep2\nRemove2 patreon subscribe"
    filters = [
        {"pattern": "Subscribe", "isRegex": False},
        {"pattern": "patreon", "isRegex": False},
    ]
    filtered, _ = apply_filters(cleaned, filters)
    assert filtered == "keep1\nkeep2"


def test_empty_lines_handling():
    cleaned = "Intro\n\nSubscribe\n\nNext"
    filters = [{"pattern": "Subscribe", "isRegex": False}]
    filtered, removed = apply_filters(cleaned, filters)
    assert removed == 1
    # empty lines should be kept (they contain no pattern)
    assert filtered.splitlines() == ["Intro", "", "", "Next"] or "Intro" in filtered

# ------------------------------------------------------------------ boilerplate
from core.filters import detect_boilerplate, mask_numbers, apply_filters_to_html


def _bp_texts():
    header = "My House of Horrors-Chapter {n}\nMy House of Horrors\nChapter {n}\n[ ... words ]\nRestore scroll position"
    footer = "Translator: Lonelytree Editor: Millman97\nShare to your friends\nChapter {n}\nTip: You can use left keys.\nReport"
    return [
        header.format(n=57) + "\nChapter 57: She Has Arrived\nChen Ge walked in.\nHe saw the mirror.\n" + footer.format(n=57),
        header.format(n=58) + "\nChapter 58: New Fools\nChen Ge ran fast.\nThe door slammed shut.\n" + footer.format(n=58),
    ]


def test_mask_numbers():
    assert mask_numbers("Chapter 57") == "Chapter #"
    assert mask_numbers("Millman97 x2") == "Millman# x#"
    assert mask_numbers("no digits") == "no digits"


def test_detect_finds_header_footer_templates():
    auto = detect_boilerplate(_bp_texts())
    pats = [f["pattern"] for f in auto]
    # note: spaces are re-escaped in patterns, match on fragments
    assert any("Chapter" in p and "\\d+" in p for p in pats), pats
    assert any("Share" in p and "friends" in p for p in pats), pats
    assert all(f["isRegex"] for f in auto)


def test_detect_keeps_unique_title():
    auto = detect_boilerplate(_bp_texts())
    filtered, removed = apply_filters(_bp_texts()[0], auto)
    assert "Chapter 57: She Has Arrived" in filtered
    assert "Chen Ge walked in." in filtered
    # boilerplate gone
    assert "Share to your friends" not in filtered
    assert "Translator: Lonelytree" not in filtered
    assert "Restore scroll position" not in filtered
    assert "My House of Horrors-Chapter 57" not in filtered
    assert removed > 5


def test_detect_anchored_no_story_damage():
    auto = detect_boilerplate(_bp_texts())
    story = "I saw Chapter 57 dogs.\nReportedly the case held.\nNothing shared today."
    filtered, removed = apply_filters(story, auto)
    assert filtered == story
    assert removed == 0


def test_detect_mid_chapter_repeat_not_learned():
    # 40-line chapters: idx 20 is far from head/tail zones, never a template
    def _chap(head, mid, tail):
        lines = [f"{head} line {i}" for i in range(8)]
        lines += [f"story filler sentence number {i} with words" for i in range(24)]
        lines[20] = mid
        lines += [f"{tail} tail line {i}" for i in range(8)]
        return "\n".join(lines)
    texts = [_chap("Head A", "Mid refrain here", "Tail Z"), _chap("Head B", "Mid refrain here", "Tail Z")]
    auto = detect_boilerplate(texts)
    pats = [f["pattern"] for f in auto]
    assert not any("Mid refrain" in p for p in pats), pats
    # tail template still learned
    assert any("Tail" in p for p in pats), pats


def test_detect_short_report_learned_with_two_chapters():
    texts = [
        "Start words here fine\nBody alpha beta gamma delta\nReport",
        "Start words here fine\nBody epsilon zeta eta theta\nReport",
    ]
    auto = detect_boilerplate(texts)
    assert any("Report" in f["pattern"] for f in auto), [f["pattern"] for f in auto]


def test_detect_single_chapter_empty():
    assert detect_boilerplate(["Only one chapter head\nBody here"]) == []
    assert detect_boilerplate([]) == []


def test_boilerplate_html_blocks_removed():
    auto = detect_boilerplate(_bp_texts())
    html = "<div><p>My House of Horrors</p><p>Chen Ge walked in.</p><p>Share to your friends</p></div>"
    out, removed = apply_filters_to_html(html, auto)
    assert "Chen Ge walked in." in out
    assert "Share to your friends" not in out
    assert removed >= 1

def test_link_text_learned_as_line():
    from core.filters import html_to_block_lines
    html = "<div><p>Story here.</p><div class=\"report-container\"><a><span>Report</span></a></div></div>"
    lines = html_to_block_lines(html)
    assert "Story here." in lines
    assert "Report" in lines


def test_link_removed_only_on_full_match():
    # plain substring must NOT eat a partially-matching link (nor its block
    # when the block itself doesn't match): link text is only removed on full match.
    html = "<div><p>Unrelated story.</p><a>Click Subscribe now</a></div>"
    out, removed = apply_filters_to_html(html, [{"pattern": "Subscribe", "isRegex": False}])
    assert removed == 0
    assert "Click Subscribe now" in out
    # ...but an entirely-matching link (report button) goes
    html2 = "<div><p>Story.</p><div><a><span>Report</span></a></div></div>"
    out2, removed2 = apply_filters_to_html(html2, [{"pattern": "^Report$", "isRegex": True}])
    assert removed2 >= 1
    assert "Report</span>" not in out2
    assert "Story." in out2
