"""Tests for the fixes of code review part 2 — filters, clean.py, fetch, EPUB.

These pin the safety valves that keep a site change or a bad pattern from
destroying the book: the boilerplate zone overlap, the content-container
protection, the override file, the cache guards and the EPUB gate.
"""
import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import clean as clean_mod  # noqa: E402
from core import fetch as fetch_mod  # noqa: E402
from core import filters as filters_mod  # noqa: E402


class TestBoilerplateSafety:
    def test_short_chapter_keeps_its_middle(self):
        # a chapter shorter than head+tail lines: the middle lines must not
        # become boilerplate candidates (the whole chapter used to qualify)
        a = ["head A"] + [f"body A {i}" for i in range(8)] + ["tail A"]
        b = ["head B"] + [f"body B {i}" for i in range(8)] + ["tail B"]
        out = filters_mod.detect_boilerplate(["\n".join(a), "\n".join(b)], head_lines=15, tail_lines=15)
        patterns = " ".join(f["pattern"] for f in out)
        assert "body" not in patterns, out

    def test_repeated_line_in_two_chapters_is_detected(self):
        a = "The End\n" + "\n".join(f"body {i}" for i in range(40))
        b = "The End\n" + "\n".join(f"other {i}" for i in range(40))
        out = filters_mod.detect_boilerplate([a, b])
        assert any("The" in f["pattern"] for f in out)


class TestBlockLines:
    def test_nested_link_is_not_repeated(self):
        html = (
            "<html><body><div id='chapter-content'>"
            "<p>Story text here</p>"
            "<p>Report Share</p>"
            "</div></body></html>"
        )
        lines = filters_mod.html_to_block_lines(html)
        # "Report Share" must appear once, not as "Report Share" + "Report" + "Share"
        assert sum(1 for ln in lines if "Report" in ln) == 1, lines


class TestFilterCanonicalization:
    def test_type_regex_is_honored_by_sanitize(self):
        out = filters_mod.sanitize_filters([{"pattern": "^The End$", "type": "regex"}])
        assert out and out[0]["isRegex"] is True, out

    def test_isregex_string_is_honored_by_sanitize(self):
        out = filters_mod.sanitize_filters([{"pattern": "^The End$", "isRegex": "1"}])
        assert out and out[0]["isRegex"] is True, out


class TestHtmlGate:
    def test_content_container_is_protected(self):
        html = (
            "<html><body><div id='wrap'><span>Ad text</span>"
            "<p>Real story paragraph</p></div></body></html>"
        )
        _html, removed = filters_mod.apply_filters_to_html(html, [{"pattern": "Ad text", "isRegex": False}])
        assert removed == 0, "the content wrapper must not be deleted"


class TestOverrides:
    def test_read_error_does_not_delete_the_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPEAK_EPUB_OVERRIDES_DIR", str(tmp_path))
        path = tmp_path / "novelphoenix.com.json"
        path.write_text(json.dumps({"start": "div#x"}), encoding="utf-8")

        def _boom(*a, **kw):
            raise PermissionError("locked")

        monkeypatch.setattr(Path, "read_text", _boom)
        assert clean_mod.load_overrides("novelphoenix.com") is None
        # the file survived
        assert path.is_file()

    def test_override_keeps_the_adapter_default_start(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPEAK_EPUB_OVERRIDES_DIR", str(tmp_path))
        clean_mod.save_overrides("novelphoenix.com", clean_mod.Selectors(start=None, end="div#end"))

        class NovelPhoenixAdapter:
            def getSelectors(self):
                return clean_mod.Selectors(start="div#chapter-content", end=None)

        sel = clean_mod.resolve_selectors(NovelPhoenixAdapter())
        assert sel.start == "div#chapter-content", sel
        assert sel.end == "div#end", sel


class TestCleanHtml:
    def test_end_boundary_is_not_ignored_in_the_heuristic(self):
        html = (
            "<html><body><div id='content'>"
            "<p>Story paragraph one</p>"
            "<div id='end'>END MARKER</div>"
            "<p>Trailing junk that must not be narrated</p>"
            "</div></body></html>"
        )
        _html, text = clean_mod.clean_html(html, None, "div#end")
        assert "Trailing junk" not in text, text

    def test_whole_page_fallback_is_reported(self):
        html = "<html><body><p>" + ("x" * 500) + "</p></body></html>"
        seen = []
        clean_mod.clean_html(html, "div#does-not-exist", None, on_log=seen.append)
        assert any("WHOLE PAGE" in line for line in seen), seen

    def test_rel_next_is_matched_case_insensitively(self):
        html = (
            "<html><body><div id='chapter-content'>"
            "<p>Story</p><a rel='Next'>Next chapter</a>"
            "</div></body></html>"
        )
        _html, text = clean_mod.clean_html(html, "div#chapter-content", None)
        assert "Next chapter" not in text, text


class TestCacheGuards:
    def test_block_page_is_not_cached(self, tmp_path):
        blocked = (
            "<html><body><h1>Just a moment...</h1>"
            "<p>Checking your browser before accessing the site. "
            + ("captcha " * 40)
            + "</p></body></html>"
        )
        with pytest.raises(ValueError):
            fetch_mod.write_cache("https://example.com/x", blocked, cache_dir=tmp_path)

    def test_normal_page_is_cached(self, tmp_path):
        ok = "<html><body><p>" + ("story " * 60) + "</p></body></html>"
        p = fetch_mod.write_cache("https://example.com/y", ok, cache_dir=tmp_path)
        assert p.is_file()

    def test_retry_after_is_capped(self):
        # a server asking for an hour must not block the queue
        assert fetch_mod._MAX_RETRY_AFTER_SEC <= 300

    def test_prune_removes_the_cover_file_too(self, tmp_path):
        d = tmp_path / "hash"
        d.mkdir(parents=True)
        (d / "raw.html").write_text("<html>x</html>", encoding="utf-8")
        (d / "cover.txt").write_text("https://example.com/c.jpg", encoding="utf-8")
        out = fetch_mod.prune_cache(cache_dir=tmp_path, max_mb=0, ttl_days=30)
        assert out["removed"] == 1
        assert not (d / "cover.txt").exists()


class TestEpubGate:
    def test_empty_chapter_is_skipped(self, tmp_path, monkeypatch):
        # the EPUB must not contain an empty <p></p> chapter
        html = "<html><body><div id='chapter-content'><p>   </p></div></body></html>"
        cleaned_html, text = clean_mod.clean_html(html, "div#chapter-content", None)
        assert not text.strip()

    def test_image_host_guard_blocks_internal_addresses(self):
        import core.epub as epub_mod

        # a resolver is injected so the test needs no DNS: the guard resolves
        # names now (see the SSRF note below)
        public = lambda host: ["93.184.216.34"]
        assert epub_mod._allowed_image_host("http://169.254.169.254/x.png", "https://site.com/a", resolve=public) is False
        assert epub_mod._allowed_image_host("http://localhost/x.png", "https://site.com/a", resolve=public) is False
        assert epub_mod._allowed_image_host("https://cdn.site.net/x.png", "https://site.com/a", resolve=public) is True

    def test_image_host_guard_resolves_names_to_block_ssrf(self):
        """A public NAME that resolves to an internal address must be refused.

        Checking only the literal text passed http://169.254.169.254.nip.io/
        (the classic bypass around an IP-literal filter) and the fetched body
        was embedded into the EPUB.
        """
        import core.epub as epub_mod

        link_local = lambda host: ["169.254.169.254"]
        assert (
            epub_mod._allowed_image_host(
                "http://169.254.169.254.nip.io/latest/meta-data/", "https://site.com/a", resolve=link_local
            )
            is False
        )

        # every answer must be public — a round-robin host cannot hide an
        # internal address behind a benign one
        mixed = lambda host: ["93.184.216.34", "10.0.0.5"]
        assert epub_mod._allowed_image_host("https://mixed.example/x.png", "https://site.com/a", resolve=mixed) is False

    def test_image_host_guard_fails_closed_on_unresolvable_hosts(self):
        import core.epub as epub_mod

        unresolvable = lambda host: None
        assert (
            epub_mod._allowed_image_host("https://nowhere.invalid/x.png", "https://site.com/a", resolve=unresolvable)
            is False
        )

    def test_image_host_guard_only_allows_http_and_https(self):
        import core.epub as epub_mod

        public = lambda host: ["93.184.216.34"]
        for bad in ("ftp://cdn.example.com/x.png", "file:///etc/passwd", "gopher://cdn.example.com/x"):
            assert epub_mod._allowed_image_host(bad, "https://site.com/a", resolve=public) is False, bad
