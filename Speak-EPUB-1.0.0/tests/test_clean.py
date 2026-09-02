"""Tests for core/clean.py — I/O matrix Story 2.2.

Covers selector hit, heuristic fallback, empty, invalid selector, end selector, strip, override atomic.
"""
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from bs4 import BeautifulSoup

from core.clean import clean_html, resolve_selectors, save_overrides, load_overrides, clear_overrides
from core.ports import Selectors

RAW_SELECTOR = """
<html><body>
<h1>Chapter 1</h1>
<div id="chapter-content"><p>Real text.</p><script>alert('bad')</script><nav>nav chrome</nav><style>bad</style></div>
<article><p>Heuristic should not be used</p></article>
</body></html>
"""

RAW_HEURISTIC = """
<html><body>
<article><p>Heuristic article text.</p><script>bad</script></article>
</body></html>
"""

RAW_HEURISTIC_CONTENT = """
<html><body>
<div class="chapter-content"><p>Heuristic div</p></div>
</body></html>
"""

RAW_EMPTY = """
<html><body><div><p></p><script>ads</script></div></body></html>
"""

RAW_END = """
<html><body>
<div id="start">START<p>First part</p></div>
<p>middle</p>
<div id="end">END</div>
<p>after</p>
</body></html>
"""

RAW_END_SIBLING = """
<html><body>
<div id="start">A</div>
<div class="mid">B</div>
<div id="end">C</div>
<div>D</div>
</body></html>
"""


def test_selector_hit_source_of_truth():
    html, text = clean_html(RAW_SELECTOR, "div#chapter-content", None)
    assert "Real text" in text
    assert "alert" not in text
    assert "nav chrome" not in text
    assert "Heuristic should not be used" not in text
    assert "<script" not in html
    assert "Real text" in html

def test_heuristic_fallback_when_selector_missing():
    html, text = clean_html(RAW_HEURISTIC, "div#chapter-content", None)
    assert "Heuristic article text" in text
    assert "bad" not in text

def test_heuristic_subfallback_content_class():
    html, text = clean_html(RAW_HEURISTIC_CONTENT, "div#chapter-content", None)
    assert "Heuristic div" in text

def test_empty_isolation_fallback_body():
    html, text = clean_html(RAW_EMPTY, "div#chapter-content", None)
    # body fallback may be empty or whitespace; ensure no error and returns strings
    assert isinstance(html, str)
    assert isinstance(text, str)
    # empty case returns at least empty string not None
    # For RAW_EMPTY, body after strip may be empty
    # Check that clean does not raise

def test_empty_preview_flag():
    # simulate preview empty: text == ""
    _, text = clean_html("<html><body><div id='chapter-content'></div></body></html>", "div#chapter-content", None)
    # fallback to heuristic/body may still empty, but function returns body html/text (maybe empty)
    assert isinstance(text, str)

def test_invalid_selector_raises():
    with pytest.raises(ValueError) as exc:
        clean_html(RAW_SELECTOR, "???", None)
    assert "invalid selector" in str(exc.value)

def test_invalid_end_selector_raises():
    with pytest.raises(ValueError):
        clean_html(RAW_SELECTOR, "div#chapter-content", "???")

def test_end_selector_sibling_walk():
    html, text = clean_html(RAW_END_SIBLING, "#start", "#end")
    assert "A" in text
    assert "B" in text
    assert "C" not in text  # end exclusive
    assert "D" not in text

def test_end_missing_fallback_start_only():
    html, text = clean_html(RAW_END, "#start", "#missing")
    assert "START" in text or "First part" in text

def test_strip_script_style_nav_aside():
    raw = '<html><body><div id="chapter-content"><p>Keep</p><script>bad</script><style>bad</style><nav>nav</nav><aside>aside</aside></div></body></html>'
    html, text = clean_html(raw, "div#chapter-content", None)
    assert text == "Keep"
    assert "<script" not in html
    assert "<nav" not in html

def test_none_start_uses_heuristic():
    html, text = clean_html(RAW_HEURISTIC, None, None)
    assert "Heuristic article text" in text

def test_empty_start_string_uses_heuristic():
    html, text = clean_html(RAW_HEURISTIC, "", None)
    assert "Heuristic article text" in text

def test_whitespace_normalization():
    raw = '<html><body><div id="chapter-content"><p>  Hello   \n\n  world   </p></div></body></html>'
    _, text = clean_html(raw, "div#chapter-content", None)
    assert text == "Hello world"

def test_resolve_selectors_default():
    mock_adapter = Mock()
    mock_adapter.getSelectors.return_value = Selectors(start="div#chapter-content", end=None)
    mock_adapter.__class__.__name__ = "NovelPhoenixAdapter"
    # ensure clean overrides not present
    clear_overrides("novelphoenix.com")
    sel = resolve_selectors(mock_adapter)
    assert sel.start == "div#chapter-content"
    assert sel.end is None

def test_override_atomic_save_load():
    clear_overrides("novelphoenix.com")
    sel = Selectors(start=".novel-text", end=None)
    p = save_overrides("novelphoenix.com", sel)
    assert p.is_file()
    # check json content
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["start"] == ".novel-text"
    loaded = load_overrides("novelphoenix.com")
    assert loaded is not None
    assert loaded.start == ".novel-text"
    # resolve should return override now
    mock_adapter = Mock()
    mock_adapter.getSelectors.return_value = Selectors(start="div#chapter-content", end=None)
    mock_adapter.__class__.__name__ = "NovelPhoenixAdapter"
    eff = resolve_selectors(mock_adapter)
    assert eff.start == ".novel-text"
    # cleanup
    clear_overrides("novelphoenix.com")
    assert not p.is_file()

def test_clear_overrides():
    save_overrides("novelphoenix.com", Selectors(start="a", end=None))
    assert load_overrides("novelphoenix.com") is not None
    cleared = clear_overrides("novelphoenix.com")
    assert cleared is True
    assert load_overrides("novelphoenix.com") is None
    # second clear returns False
    assert clear_overrides("novelphoenix.com") is False

def test_resolve_never_overwrites_adapter_file():
    # ensure adapter file still has original selector
    from pathlib import Path
    p = Path("Speak-EPUB-1.0.0/adapters/novelphoenix.py")
    # read file to ensure getSelectors still returns div#chapter-content
    txt = p.read_text(encoding="utf-8")
    assert 'start="div#chapter-content"' in txt

def test_raw_not_filtered_invariant():
    # ensure raw still contains nav after clean (clean does not mutate raw)
    raw = RAW_SELECTOR
    html, text = clean_html(raw, "div#chapter-content", None)
    assert "nav chrome" in raw  # raw invariant
    assert "nav chrome" not in text
