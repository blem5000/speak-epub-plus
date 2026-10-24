"""Tests for core/epub.py embed_chapter_images (step 6: images in EPUB).

Offline: download is injected, no network, no cache.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PARENT = ROOT.parent
if str(PARENT) not in sys.path:
    sys.path.insert(0, str(PARENT))

from core.epub import embed_chapter_images

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
JPG = b"\xff\xd8\xff" + b"\x00" * 100


def _fake_dl(mapping):
    def _dl(url):
        return mapping.get(url)
    return _dl


def _public(host):
    """Resolver stub: pretend every name is a public address (no DNS)."""
    return ["93.184.216.34"]


class TestEmbedChapterImages:
    def test_remote_img_embedded_and_src_rewritten(self):
        html = '<div><p>Text</p><img src="https://cdn.example.com/a.png" alt="A"/></div>'
        out, items, embedded, skipped = embed_chapter_images(
            html, "https://novelphoenix.com/novel/x/chapter-1", 1,
            download=_fake_dl({"https://cdn.example.com/a.png": (PNG, "png")}), resolve=_public,
        )
        assert embedded == 1
        assert skipped == 0
        assert len(items) == 1
        uid, fname, mtype, data = items[0]
        assert fname == "images/ch001_01.png"
        assert mtype == "image/png"
        assert data == PNG
        assert 'src="images/ch001_01.png"' in out
        assert "cdn.example.com" not in out

    def test_relative_src_resolved_and_srcset_dropped(self):
        html = '<div><img src="/img/b.jpg" srcset="https://cdn.example.com/b2.jpg 2x" sizes="100vw"/></div>'
        out, items, embedded, skipped = embed_chapter_images(
            html, "https://novelphoenix.com/novel/x/chapter-2", 2,
            download=_fake_dl({"https://novelphoenix.com/img/b.jpg": (JPG, "jpg")}),
        )
        assert embedded == 1
        assert "srcset" not in out
        assert "images/ch002_01.jpg" in out

    def test_data_url_kept_and_failures_keep_remote(self):
        html = (
            '<div><img src="data:image/png;base64,AAA"/>'
            '<img src="https://cdn.example.com/missing.png"/>'
            '<img src="/local/ok.png"/></div>'
        )
        out, items, embedded, skipped = embed_chapter_images(
            html, "https://novelphoenix.com/novel/x/chapter-3", 3,
            download=_fake_dl({"https://novelphoenix.com/local/ok.png": (PNG, "png")}),
        )
        assert embedded == 1
        assert skipped == 1  # missing.png
        assert "data:image/png;base64,AAA" in out  # untouched, not counted
        assert "https://cdn.example.com/missing.png" in out  # kept remote

    def test_non_http_and_empty_skipped(self):
        html = '<div><img src="ftp://x/y.png"/><img/><img src="  "/></div>'
        out, items, embedded, skipped = embed_chapter_images(html, "https://n/x/chapter-1", 1, download=_fake_dl({}))
        assert embedded == 0
        assert skipped == 3
        assert items == []

    def test_max_images_cap(self):
        html = "<div>" + "".join(f'<img src="https://c.example.com/{i}.png"/>' for i in range(25)) + "</div>"
        mapping = {f"https://c.example.com/{i}.png": (PNG, "png") for i in range(25)}
        out, items, embedded, skipped = embed_chapter_images(
            html, "https://n/x/chapter-1", 1, download=_fake_dl(mapping), max_images=20, resolve=_public
        )
        assert embedded == 20
        assert len(items) == 20

    def test_no_imgs_returns_unchanged(self):
        html = "<div><p>No images here</p></div>"
        out, items, embedded, skipped = embed_chapter_images(html, "https://n/x/chapter-1", 1, download=_fake_dl({}))
        assert (out, items, embedded, skipped) == (html, [], 0, 0)
