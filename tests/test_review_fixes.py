"""tests/test_review_fixes.py — pins for H/M review fixes (M6).

Covers: H1 merge-failure part survival, H5 multi-novel + epubcheck fail,
H8 lord mock gating, M1 cache/retry helpers, M5 prune, diacritics slug,
heartbeat contract, H6 resume lock.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def test_h1_failed_merge_keeps_parts(tmp_path, capsys):
    from core.tts import ChapterPlan, finalize_chapter_audio

    out = tmp_path / "h1"
    out.mkdir()
    parts = out / "_parts"
    parts.mkdir()
    p1 = parts / "040_C40_part001.mp3"
    p2 = parts / "040_C40_part002.mp3"
    p1.write_bytes(b"p1" * 2048)
    p2.write_bytes(b"p2" * 2048)
    chapter_mp3 = out / "040_C40.mp3"
    plan = ChapterPlan(40, "C40", str(chapter_mp3), [str(p1), str(p2)],
                       [(40, "C40 - part 1", str(p1)), (40, "C40 - part 2", str(p2))])

    def failing_concat(paths, out_path):
        raise subprocess.CalledProcessError(returncode=1, cmd="ffmpeg")

    with patch("core.tts.ffmpeg_available", return_value=True):
        with patch("core.tts.concat_mp3_files", side_effect=failing_concat):
            entries = finalize_chapter_audio([plan], keep_parts=False)
    assert entries == [(40, "C40 - part 1", str(p1)), (40, "C40 - part 2", str(p2))]
    # H1: fallback entries must reference live files
    assert p1.is_file() and p2.is_file()
    assert not chapter_mp3.exists()


def test_h5_get_epub_status_multi_novel_and_epubcheck_fail(tmp_path, monkeypatch):
    import time

    import core.config as cfg

    out = tmp_path / "epubs"
    out.mkdir()
    a = out / "Lord_of_Mysteries_chapters_001_to_002.epub"
    b = out / "Other_Book_chapters_001_to_002.epub"
    a.write_bytes(b"A" * 100)
    time.sleep(0.02)
    b.write_bytes(b"B" * 100)  # B newer by mtime

    req_a = {"id": "1", "method": "getEpubStatus",
             "params": {"novelUrl": "https://www.novelphoenix.com/novel/123-lord-of-mysteries",
                        "outputDir": str(out)}}
    res_a = cfg.handle_rpc(req_a)
    assert res_a["result"]["exists"] is True
    # H5: must return novel A even though B is newer
    assert Path(res_a["result"]["path"]).name == a.name

    # H5: epubcheck raise surfaces as ok False (not True)
    with patch("core.epub.run_epubcheck", side_effect=RuntimeError("boom")):
        res2 = cfg.handle_rpc(req_a)
    assert res2["result"]["epubcheck_ok"] is False
    assert res2["result"]["messages"]


def test_h8_no_lord_mock_empty_stays_empty(monkeypatch):
    """H8 removal pin: search with no adapter hits returns [] — no fabricated
    Lord of Mysteries rows, with or without any env flag."""
    import core.config as cfg

    monkeypatch.delenv("SPEAK_LORD_MOCK", raising=False)
    for title in ("Lord of Mysteries", "Overlord adventure", "zzzz_no_match"):
        req = {"id": "1", "method": "search", "params": {"title": title}}
        with patch("core.aggregator.search_all", return_value=[]):
            res = cfg.handle_rpc(req)
        assert res["result"] == [], title
    monkeypatch.setenv("SPEAK_LORD_MOCK", "1")
    req = {"id": "2", "method": "search", "params": {"title": "Lord of Mysteries"}}
    with patch("core.aggregator.search_all", return_value=[]):
        res = cfg.handle_rpc(req)
    assert res["result"] == []
    monkeypatch.delenv("SPEAK_LORD_MOCK", raising=False)


def test_m1_write_cache_rejects_non_html(tmp_path):
    from core.fetch import write_cache

    with pytest.raises(ValueError):
        write_cache("https://x.com/n/1", "SearchResult(site=...) repr, no tags", tmp_path)


def test_m1_normalize_strips_default_ports_and_guards():
    from core.fetch import _normalize_cache_key as f_norm
    import core.config as cfg

    assert f_norm("http://example.com:80/novel/1") == f_norm("http://example.com/novel/1")
    assert f_norm("https://example.com:443/novel/1") == f_norm("https://example.com/novel/1")
    assert f_norm("http://example.com:8080/novel/1") != f_norm("http://example.com/novel/1")
    assert f_norm(123) == ""  # type: ignore[arg-type]
    assert cfg._normalize_cache_key(123) == ""  # type: ignore[arg-type]
    # delegation: same result both modules
    u = "https://www.novelphoenix.com/novel/123-lord-of-mysteries?x=1#frag"
    assert cfg._normalize_cache_key(u) == f_norm(u)


def test_m1_http_status_context_and_int_code():
    from core.fetch import _http_status

    class E(Exception):
        pass

    # int code attribute
    e = E("fail")
    e.code = 429  # type: ignore[attr-defined]
    assert _http_status(e) == 429

    # 429 via __context__ (not just __cause__)
    inner = E("inner")
    inner.code = "429 Too Many"  # type: ignore[attr-defined]
    outer = E("outer")
    outer.__context__ = inner
    assert _http_status(outer) == 429

    # .status attribute (aiohttp-style)
    e2 = E("x")
    e2.status = 503  # type: ignore[attr-defined]
    assert _http_status(e2) == 503


def test_m1_exc_code_prefers_attrs():
    import core.config as cfg

    class E(Exception):
        pass

    e = E("https://site.com/chapter/500 happened")
    e.code = "FETCH_FAILED"  # type: ignore[attr-defined]
    assert cfg._exc_code(e) == "FETCH_FAILED"
    assert cfg._is_code(e, "FETCH_FAILED") is True
    # URL-embedded number must not misfire without code attr
    e2 = E("failed for https://site.com/chapter/500")
    assert cfg._is_code(e2, "LIST_FAILED") is False


def test_m5_prune_cache_ttl(tmp_path):
    import time

    from core.fetch import get_cache_path, prune_cache

    u_old = "https://site.com/novel/old-1"
    u_new = "https://site.com/novel/new-1"
    p_old = get_cache_path(u_old, tmp_path)
    p_old.parent.mkdir(parents=True, exist_ok=True)
    p_old.write_text("<html>old</html>", encoding="utf-8")
    old_t = time.time() - 40 * 86400
    os.utime(p_old, (old_t, old_t))
    p_new = get_cache_path(u_new, tmp_path)
    p_new.parent.mkdir(parents=True, exist_ok=True)
    p_new.write_text("<html>new</html>", encoding="utf-8")

    res = prune_cache(tmp_path, max_mb=500, ttl_days=30)
    assert res["removed"] >= 1
    assert not p_old.exists()
    assert p_new.exists()


def test_diacritics_slug_safe():
    from core.epub import _slug_from_title, sanitize_filename

    slug = _slug_from_title("Żółć Łódź ąęść", fallback="book")
    assert slug and slug != "book"
    # filesystem-safe: no reserved chars
    assert sanitize_filename(slug) == slug
    assert len(slug) <= 60


def test_heartbeat_contract():
    from core.audio import _HEARTBEAT_SEC

    # Rust sidecar timeout is 300s — heartbeat must stay well under it
    assert _HEARTBEAT_SEC < 300
    assert _HEARTBEAT_SEC <= 60


def test_h6_resume_lock_blocks_concurrent(tmp_path):
    from core.tts import acquire_resume_lock, release_resume_lock

    lock = acquire_resume_lock(tmp_path)
    assert lock is not None
    try:
        with pytest.raises(RuntimeError, match="concurrent resume"):
            acquire_resume_lock(tmp_path)
    finally:
        release_resume_lock(lock)
    # after release, acquirable again
    lock2 = acquire_resume_lock(tmp_path)
    assert lock2 is not None
    release_resume_lock(lock2)


def test_cache_miss_always_carries_missing():
    import core.config as cfg

    # buildEpub with explicit urls and empty cache -> CACHE_MISS with missing list
    req = {"id": "1", "method": "buildEpub",
           "params": {"novelUrl": "https://www.novelphoenix.com/novel/1-x",
                      "urls": ["https://www.novelphoenix.com/c/1", "https://www.novelphoenix.com/c/2"]}}
    res = cfg.handle_rpc(req)
    assert res["error"]["code"] == "CACHE_MISS"
    assert isinstance(res["error"].get("missing"), list)


def test_r3_resume_lock_stale_reclaim_and_unlink_fail(tmp_path, monkeypatch):
    import time as _time

    from core.tts import RESUME_LOCK_STALE_SEC, acquire_resume_lock, release_resume_lock

    lock = acquire_resume_lock(tmp_path)
    assert lock is not None
    # stale (>600s) lock is reclaimed
    old = _time.time() - (RESUME_LOCK_STALE_SEC + 100)
    os.utime(lock, (old, old))
    lock2 = acquire_resume_lock(tmp_path)
    assert lock2 is not None
    release_resume_lock(lock2)

    # undeletable stale lock → RuntimeError, never RecursionError
    lock3 = acquire_resume_lock(tmp_path)
    assert lock3 is not None
    os.utime(lock3, (old, old))
    real_unlink = Path.unlink

    def fake_unlink(self, missing_ok=False):  # type: ignore[no-untyped-def]
        if str(self) == str(lock3):
            raise OSError("locked by AV")
        return real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", fake_unlink)
    with pytest.raises(RuntimeError, match="concurrent resume"):
        acquire_resume_lock(tmp_path)
    monkeypatch.undo()
    release_resume_lock(lock3)


def test_r3_resume_root_guards_and_parts_layout():
    from core.tts import _resume_root_for_jobs

    class _J:
        def __init__(self, p):  # type: ignore[no-untyped-def]
            self.output_path = p

    assert _resume_root_for_jobs([]) is None
    assert _resume_root_for_jobs([_J(None)]) is None
    assert _resume_root_for_jobs([_J(123)]) is None
    assert _resume_root_for_jobs([_J("")]) is None
    parts_job = _J(str(Path("root_out") / "_parts" / "x.mp3"))
    assert _resume_root_for_jobs([parts_job]) == Path("root_out")


def test_r3_build_audio_chunk_size_validation(monkeypatch):
    import core.config as cfg

    base = {"novelUrl": "https://www.novelphoenix.com/novel/123"}
    for bad in (6000, 0, -5, "abc"):
        res = cfg.handle_rpc({"id": "1", "method": "buildAudio", "params": {**base, "chunkSize": bad}})
        assert res["error"]["code"] == "VALUE_ERROR", bad


def test_r3_get_epub_status_range_filter(tmp_path):
    import time

    import core.config as cfg

    out = tmp_path / "epubs"
    out.mkdir()
    a = out / "Rangebook_chapters_051_to_100.epub"
    b = out / "Rangebook_chapters_001_to_050.epub"
    a.write_bytes(b"A" * 100)  # older
    time.sleep(0.02)
    b.write_bytes(b"B" * 100)  # newer — must NOT win for range 51..100

    req = {"id": "1", "method": "getEpubStatus",
           "params": {"novelUrl": "https://www.novelphoenix.com/novel/123-rangebook",
                      "outputDir": str(out), "from": 51, "to": 100}}
    res = cfg.handle_rpc(req)
    assert res["result"]["exists"] is True
    # range filter must pick the overlapping file, not merely the newest
    assert Path(res["result"]["path"]).name == a.name
