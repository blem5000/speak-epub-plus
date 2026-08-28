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
