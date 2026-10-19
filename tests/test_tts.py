"""Tests for core/tts.py — I/O matrix Story 3.1 (ratyfikacja brownfield) + 3.2 Edge TTS + parallel + retries."""
import asyncio
import json
import os
import re
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from core.tts import (
    build_generation_plan,
    ChapterPlan,
    PartJob,
    run_part_jobs,
    resolve_output_dir,
    sanitize_filename,
    split_text_for_tts,
    split_dialogue,
    split_title_body,
    ensure_pause_file,
    check_build_identity,
    postprocess_chapter_file,
    TITLE_PAUSE_SEC,
    tts_text_to_mp3,
    verify_part_audio,
    ffmpeg_available,
    ffprobe_available,
    concat_mp3_files,
    get_duration_ms,
    escape_ffmeta,
    finalize_chapter_audio,
    build_m4b,
    AdaptiveGate,
    ADAPTIVE_GROW_AFTER,
    ADAPTIVE_MAX_PARALLEL,
    normalize_tts_rate,
)


# ---------------------------------------------------------------------------
# split_text_for_tts
# ---------------------------------------------------------------------------

def test_happy_single_gt3500_sentence_boundary():
    text = "Sentence one. " * 800  # ~11200? Actually "Sentence one. " 14 chars *800=11200
    # Use shorter to match spec: spec says "Sentence one. " *800 ~5600? but we keep 800
    # To exactly test >3500 with 2 chunks, we can use 400* 14=5600, but 800 yields ~11200 -> 4 chunks still valid
    # For spec example: use 400 repeats to get ~5600 => 2 chunks. We'll test both.
    chunks = split_text_for_tts(text, 3500)
    assert len(chunks) >= 2
    assert all(len(c) <= 3500 for c in chunks)
    # order preserved: re-joining with space should contain original sentences order
    # First chunk ends with sentence boundary ., last chunk starts with Sentence
    assert chunks[0].strip().endswith(".")
    assert chunks[1].strip().startswith("Sentence")
    # No lost characters beyond collapsed whitespace: total chars of chunks approx original collapsed length
    collapsed = re.sub(r"\s+", " ", text).strip()
    # chunks joined with " " should not equal exactly due to boundaries, but concatenated via " ".join(chunks) length close
    # Check that all chunks order preserved: reconstruct text by joining chunks with " " and compare start
    rejoined = " ".join(chunks)
    # First 20 chars should match
    assert rejoined[:20] == collapsed[:20]
    # Also check split at sentence boundary uses regex (?<=[.!?;:])\s+
    for c in chunks:
        assert len(c) <= 3500


def test_happy_spec_example_5600():
    # Spec's happy: "Sentence one. " * 800 but spec comment says ~5600 chars (maybe 400*14). Use 400
    text = "Sentence one. " * 400  # 5600
    chunks = split_text_for_tts(text, 3500)
    assert len(chunks) == 2
    assert all(len(c) <= 3500 for c in chunks)
    assert chunks[0].endswith(".")
    assert chunks[1].startswith("Sentence")


def test_hard_cut_single_sentence_4000():
    text = "a" * 4000
    chunks = split_text_for_tts(text, 3500)
    assert len(chunks) == 2
    assert chunks[0] == "a" * 3500
    assert chunks[1] == "a" * 500
    assert all(len(c) <= 3500 for c in chunks)


def test_hard_cut_longer_7001():
    text = "x" * 7001
    chunks = split_text_for_tts(text, 3500)
    assert len(chunks) == 3
    assert chunks[0] == "x" * 3500
    assert chunks[1] == "x" * 3500
    assert chunks[2] == "x" * 1
    assert all(len(c) <= 3500 for c in chunks)


def test_empty_whitespace():
    assert split_text_for_tts("   ") == []
    assert split_text_for_tts("") == []
    assert split_text_for_tts("\n\t  \n") == []
    assert split_text_for_tts("   ", 3500) == []


def test_whitespace_collapse():
    text = "Foo  \n  bar\t baz"
    chunks = split_text_for_tts(text, 3500)
    assert chunks == ["Foo bar baz"]
    # Also ensure collapse does not add extra
    assert len(chunks[0]) == len("Foo bar baz")


def test_semicolon_colon_boundary():
    # Within single chunk limit, no split needed, but verify semicolon/colon are treated as sentence ends for chunking when overflow
    text = "a; b: c. d! e? f."
    # Keep under 3500, should be single chunk preserving ;
    chunks = split_text_for_tts(text, 3500)
    assert chunks == ["a; b: c. d! e? f."]
    assert ";" in chunks[0]
    assert ":" in chunks[0]
    # For overflow, ensure split respects ; and : boundaries
    # Create text that will require split at ; and :
    # Build sentences that together exceed 3500 via ; boundaries, check no chunk >3500 and no loss
    sentence = "a; b: c. "
    repeat = 400  # ~ 9*400=3600 >3500, should split at boundary
    text2 = (sentence * repeat).strip()
    chunks2 = split_text_for_tts(text2, 3500)
    assert all(len(c) <= 3500 for c in chunks2)
    # Ensure all sentences preserved in order: count semicolons approx
    assert len(chunks2) >= 2
    # No lost sentence beyond collapsed whitespace
    collapsed = re.sub(r"\s+", " ", text2).strip()
    # The number of "a;" occurrences should be preserved
    assert collapsed.count("a;") == " ".join(chunks2).count("a;")


def test_exact_boundary_mixed():
    # Spec: "Foo! Bar? Baz; qux. " repeated to 3501 -> overflow flush
    base = "Foo! Bar? Baz; qux. "
    # Repeat to exceed 3501
    text = (base * 200).strip()  # 20*200=4000 >3500
    chunks = split_text_for_tts(text, 3500)
    assert all(len(c) <= 3500 for c in chunks)
    assert len(chunks) >= 2
    # Ensure no chunk >3500 and no lost sentence: count Foo!
    collapsed = re.sub(r"\s+", " ", text).strip()
    assert collapsed.count("Foo!") == " ".join(chunks).count("Foo!")


def test_all_chunks_le_3500_and_order():
    # Random mix
    texts = [
        "Hello world. " * 1000,
        "Sentence! " * 500 + "x" * 4000,
        "a; b: c. d! " * 300,
    ]
    for txt in texts:
        chunks = split_text_for_tts(txt, 3500)
        assert all(len(c) <= 3500 for c in chunks), "chunk exceeded 3500"
        # order preserved: joining with special marker shouldn't reorder
        collapsed = re.sub(r"\s+", " ", txt).strip()
        # Ensure first sentence still first and last still last
        if collapsed and chunks:
            first_sent = re.split(r"(?<=[.!?;:])\s+", collapsed)[0].strip()
            assert chunks[0].startswith(first_sent[:20].strip())


def test_sanitize_filename():
    assert sanitize_filename("A/B:C?D*", fallback="chapter") == "A_B_C_D_"
    assert sanitize_filename("A/B: Test?", fallback="chapter") == "A_B_ Test_"
    # speak.py:84 mirror — "///" becomes "___" not fallback (only empty after strip falls back)
    assert sanitize_filename("///", fallback="chapter") == "___"
    assert sanitize_filename("", fallback="chapter") == "chapter"
    assert len(sanitize_filename("a" * 100, max_len=60)) == 60
    # fallback with max_len and strip
    assert sanitize_filename("   ", fallback="fallback") == "fallback"
    # whitespace collapse
    assert sanitize_filename("  a   b  ", fallback="chapter") == "a b"


# ---------------------------------------------------------------------------
# build_generation_plan
# ---------------------------------------------------------------------------

def test_single_chunk_plan(tmp_path):
    chapters = [(5, "T", "Hello world")]
    out = str(tmp_path / "out")
    os.makedirs(out, exist_ok=True)
    plans, jobs = build_generation_plan(chapters, out, 3500)
    assert len(plans) == 1
    assert len(jobs) == 1
    plan = plans[0]
    job = jobs[0]
    # chapter_mp3 basename
    assert Path(plan.chapter_mp3).name == "005_T.mp3"
    assert Path(job.output_path).name == "005_T.mp3"
    assert job.chapter_number == 5
    assert job.part_number == 1
    assert job.part_count == 1
    assert job.text == "Hello world"
    assert job.is_final_chapter_file is True
    # Not in _parts
    assert "_parts" not in job.output_path
    assert "_parts" not in plan.chapter_mp3
    assert plan.part_paths == [plan.chapter_mp3]
    assert plan.marker_entries_if_unmerged == [(5, "T", plan.chapter_mp3)]
    # Check frozen
    assert job.chapter_title == "T"


def test_multi_chunk_plan_global_order(tmp_path):
    # Build deterministic multi: use hard-cut texts to force known chunk counts
    # 7001 chars -> 3 chunks via hard cut, but to get 2 chunks use 6000? Use 7000 for 2 chunks?
    # To exactly test spec's example (40 ->2, 41->1, 42->2) we can use curated sizes via chunk logic:
    # Instead test generic property: global order reading-order.
    # We'll create chapters where we know chunk counts via split_text_for_tts.
    text_2chunks = "a" * 4000  # 2 chunks
    text_1chunk = "hello"
    text_3chunks = "b" * 7001  # 3 chunks
    chapters = [
        (40, "C40", text_2chunks),
        (41, "C41", text_1chunk),
        (42, "C42", text_2chunks),
    ]
    out = str(tmp_path / "out")
    os.makedirs(out, exist_ok=True)
    # Predict chunks
    c40_chunks = split_text_for_tts(text_2chunks, 3500)
    c41_chunks = split_text_for_tts(text_1chunk, 3500)
    c42_chunks = split_text_for_tts(text_2chunks, 3500)
    assert len(c40_chunks) == 2
    assert len(c41_chunks) == 1
    assert len(c42_chunks) == 2
    plans, jobs = build_generation_plan(chapters, out, 3500)
    # Expected jobs: 2 +1 +2 =5 but single-chunk jobs are is_final True and path not in _parts
    # multi-part jobs have is_final False and path in _parts
    # Global order: ch40 p1, p2, ch41 p1, ch42 p1, p2
    assert len(jobs) == 5
    assert jobs[0].chapter_number == 40 and jobs[0].part_number == 1
    assert jobs[1].chapter_number == 40 and jobs[1].part_number == 2
    assert jobs[2].chapter_number == 41 and jobs[2].part_number == 1
    assert jobs[3].chapter_number == 42 and jobs[3].part_number == 1
    assert jobs[4].chapter_number == 42 and jobs[4].part_number == 2
    # Verify is_final flags
    assert jobs[0].is_final_chapter_file is False
    assert jobs[1].is_final_chapter_file is False
    assert jobs[2].is_final_chapter_file is True  # single
    assert jobs[3].is_final_chapter_file is False
    assert jobs[4].is_final_chapter_file is False
    # part_paths for multi should be under _parts and contain safe title
    for plan in plans:
        if len(split_text_for_tts(chapters[plan.chapter_number - 40][2] if plan.chapter_number in (40,42) else text_1chunk, 3500)) > 1:
            # multi
            for p in plan.part_paths:
                assert Path(p).parent.name == "_parts"
                assert f"{plan.chapter_number:03d}_" in Path(p).name
        else:
            # single
            assert len(plan.part_paths) == 1
            assert Path(plan.part_paths[0]).parent.name != "_parts"


def test_multi_chunk_spec_7001_order(tmp_path):
    # Test the spec's 7001* example: 7001 -> 3 chunks, so 3+1+3=7 jobs, order still reading order
    chapters = [(40, "C40", "x" * 7001), (41, "C41", "y" * 2000), (42, "C42", "z" * 7001)]
    out = str(tmp_path / "out2")
    os.makedirs(out, exist_ok=True)
    plans, jobs = build_generation_plan(chapters, out, 3500)
    # 7001 hard cut -> 3 each
    assert len(split_text_for_tts("x" * 7001, 3500)) == 3
    # Jobs: 3 +1 +3 =7
    assert len(jobs) == 7
    # Order check: first 3 are ch40 p1..3 before ch41 p1
    assert jobs[0].chapter_number == 40 and jobs[0].part_number == 1
    assert jobs[1].chapter_number == 40 and jobs[1].part_number == 2
    assert jobs[2].chapter_number == 40 and jobs[2].part_number == 3
    assert jobs[3].chapter_number == 41
    assert jobs[4].chapter_number == 42 and jobs[4].part_number == 1


def test_output_path_sanitize(tmp_path):
    chapters = [(3, "A/B:C?D*", "Hello world part that is short")]
    # Duplicate to test multi part also sanitized
    # For multi test, make text long to force part files
    chapters_long = [(3, "A/B:C?D*", "a" * 4000)]
    out = str(tmp_path / "out")
    os.makedirs(out, exist_ok=True)
    # single chunk
    plans, jobs = build_generation_plan(chapters, out, 3500)
    assert Path(plans[0].chapter_mp3).name == "003_A_B_C_D_.mp3"
    assert Path(jobs[0].output_path).name == "003_A_B_C_D_.mp3"
    # multi chunk part files also sanitized
    plans2, jobs2 = build_generation_plan(chapters_long, out, 3500)
    for p in plans2[0].part_paths:
        assert "A_B_C_D_" in Path(p).name
        assert p.endswith(".mp3")
        assert Path(p).parent.name == "_parts"
        assert f"003_A_B_C_D__part" in Path(p).name
    for j in jobs2:
        assert "A_B_C_D_" in Path(j.output_path).name
        assert Path(j.output_path).parent.name == "_parts"


def test_sanitize_fallback_empty_title(tmp_path):
    # Empty after sanitization triggers fallback — speak.py:84 returns fallback when safe becomes ""
    chapters = [(3, "   ", "Hello")]
    out = str(tmp_path / "out")
    os.makedirs(out, exist_ok=True)
    plans, jobs = build_generation_plan(chapters, out, 3500)
    # fallback Chapter_003
    assert Path(plans[0].chapter_mp3).name == "003_Chapter_003.mp3"
    # "///" does NOT fallback in speak mirror — it becomes "___"
    chapters2 = [(3, "///", "Hello")]
    out2 = str(tmp_path / "out2")
    os.makedirs(out2, exist_ok=True)
    plans2, _ = build_generation_plan(chapters2, out2, 3500)
    assert Path(plans2[0].chapter_mp3).name == "003____.mp3"


def test_frozen_immutability():
    job = PartJob(
        chapter_number=1,
        chapter_title="T",
        part_number=1,
        part_count=1,
        text="hello",
        output_path="/tmp/out.mp3",
        is_final_chapter_file=True,
    )
    with pytest.raises(FrozenInstanceError):
        job.text = "x"
    with pytest.raises(FrozenInstanceError):
        job.output_path = "y"
    # Also test hash stability
    assert hash(job) is not None
    # Check required fields present
    for field in ["chapter_number", "part_number", "part_count", "text", "output_path", "is_final_chapter_file"]:
        assert hasattr(job, field)
    # chapter_title retained for compat
    assert hasattr(job, "chapter_title")
    assert job.chapter_title == "T"
    # Verify frozen dataclass attribute
    assert getattr(PartJob, "__dataclass_params__").frozen is True  # type: ignore[attr-defined]


def test_existing_file_skip_guard(tmp_path, monkeypatch):
    # hermetic: fake fixture files have no real audio duration to probe
    monkeypatch.setattr("core.tts.ffprobe_available", lambda: False)
    out = str(tmp_path / "out")
    os.makedirs(out, exist_ok=True)
    part_dir = Path(out) / "_parts"
    part_dir.mkdir(parents=True, exist_ok=True)
    # Create chapters with 2 parts each
    chapters = [(40, "C40", "a" * 4000), (41, "C41", "b" * 4000)]
    # Pre-create part file for ch40 p1 to simulate resume
    # Need to know safe title; for "C40" it's "C40"
    pre_part = part_dir / "040_C40_part001.mp3"
    pre_part.write_text("x" * 2048, encoding="utf-8")
    # Also test chapter_mp3 existence skip
    # For single chunk case, pre-create chapter mp3
    # Now build plan
    plans, jobs = build_generation_plan(chapters, out, 3500)
    # Jobs should NOT contain the existing part
    job_paths = [Path(j.output_path).name for j in jobs]
    assert "040_C40_part001.mp3" not in job_paths
    # But should contain the other parts: 040 p2, 041 p1,p2 (unless chapter_mp3 exists check)
    # Since chapter_mp3 not exists, both chapters' missing parts should be queued except existing
    assert "040_C40_part002.mp3" in job_paths
    assert "041_C41_part001.mp3" in job_paths
    assert "041_C41_part002.mp3" in job_paths
    # Also test that if chapter_mp3 exists, no jobs for that chapter
    # Create chapter mp3 for 041 single? But 041 is multi (2 parts) so chapter_mp3 is 041_C41.mp3
    chapter_mp3_path = Path(out) / "041_C41.mp3"
    chapter_mp3_path.write_text("x" * 2048, encoding="utf-8")
    plans2, jobs2 = build_generation_plan(chapters, out, 3500)
    # Now jobs for chapter 041 should be empty because chapter_mp3 exists (guard: not exists(chapter_mp3) and not exists(part_path))
    job_ch41 = [j for j in jobs2 if j.chapter_number == 41]
    assert len(job_ch41) == 0
    # ch40 second part still queued (since chapter_mp3 not exists and part002 not exists)
    job_ch40 = [j for j in jobs2 if j.chapter_number == 40]
    # p1 exists, p2 queued
    assert len(job_ch40) == 1
    assert job_ch40[0].part_number == 2


def test_single_chunk_not_in_parts(tmp_path):
    chapters = [(5, "Title", "short")]
    out = str(tmp_path / "out")
    os.makedirs(out, exist_ok=True)
    plans, jobs = build_generation_plan(chapters, out, 3500)
    # For single chunk, output should be chapter_mp3 directly, not inside _parts subfolder
    assert Path(jobs[0].output_path).parent == Path(out)
    assert Path(jobs[0].output_path).name == "005_Title.mp3"
    assert Path(plans[0].chapter_mp3).parent == Path(out)
    # Ensure _parts not in parts list
    assert jobs[0].output_path.endswith("005_Title.mp3")
    # Ensure _parts dir may not be created for single chunk? Actually build creates part_dir only for multi, so not created
    assert not (Path(out) / "_parts" / "005_Title_part001.mp3").exists()


def test_chapterplan_fields(tmp_path):
    chapters = [(1, "T1", "a" * 4000), (2, "T2", "hello")]
    out = str(tmp_path / "out")
    os.makedirs(out, exist_ok=True)
    plans, jobs = build_generation_plan(chapters, out, 3500)
    assert len(plans) == 2
    # Check types
    for plan in plans:
        assert isinstance(plan, ChapterPlan)
        assert isinstance(plan.chapter_number, int)
        assert isinstance(plan.title, str)
        assert isinstance(plan.chapter_mp3, str)
        assert isinstance(plan.part_paths, list)
        assert isinstance(plan.marker_entries_if_unmerged, list)


def test_empty_text_plan(tmp_path):
    chapters = [(1, "Empty", "   "), (2, "Normal", "Hello")]
    out = str(tmp_path / "out")
    os.makedirs(out, exist_ok=True)
    plans, jobs = build_generation_plan(chapters, out, 3500)
    assert len(plans) == 2
    assert plans[0].part_paths == []
    assert plans[0].marker_entries_if_unmerged == []
    # no job for empty
    assert all(j.chapter_number != 1 for j in jobs)
    assert any(j.chapter_number == 2 for j in jobs)


def test_partjob_fields_presence():
    # Ensure PartJob has 6 required fields
    fields = PartJob.__dataclass_fields__  # type: ignore[attr-defined]
    required = ["chapter_number", "part_number", "part_count", "text", "output_path", "is_final_chapter_file"]
    for f in required:
        assert f in fields, f"missing required field {f}"
    # chapter_title retained
    assert "chapter_title" in fields


def test_single_chunk_resume_skip(tmp_path, monkeypatch):
    """Single-chunk chapter MP3 already exists → jobs == [] (resume)."""
    # hermetic: fake fixture file has no real audio duration to probe
    monkeypatch.setattr("core.tts.ffprobe_available", lambda: False)
    out = str(tmp_path / "out_resume_single")
    os.makedirs(out, exist_ok=True)
    # single-chunk chapter (short text)
    chapters = [(5, "T", "Hello world")]
    # predict chapter_mp3 name
    safe = sanitize_filename("T", fallback="Chapter_005")
    chapter_mp3 = Path(out) / f"005_{safe}.mp3"
    chapter_mp3.write_text("x" * 2048, encoding="utf-8")
    plans, jobs = build_generation_plan(chapters, out, 3500)
    assert jobs == [], "single-chunk resume should skip existing chapter MP3"
    assert len(plans) == 1
    assert Path(plans[0].chapter_mp3).name == "005_T.mp3"
    assert plans[0].part_paths == [str(chapter_mp3)]


def test_parts_dir_created_on_multi(tmp_path):
    """Fresh multi-chunk build must create output_dir/_parts dir."""
    out = str(tmp_path / "out_parts_check")
    os.makedirs(out, exist_ok=True)
    chapters = [(40, "C40", "a" * 4000)]  # 2 chunks
    parts_dir = Path(out) / "_parts"
    assert not parts_dir.exists()
    plans, jobs = build_generation_plan(chapters, out, 3500)
    assert len(jobs) == 2
    assert parts_dir.is_dir(), "build_generation_plan should mkdir _parts for multi"
    for j in jobs:
        assert Path(j.output_path).parent == parts_dir
        assert j.output_path.startswith(out)


# ---------------------------------------------------------------------------
# Story 3.2 — Edge TTS + parallel 2–3 + retries + _parts skip
# ---------------------------------------------------------------------------


def test_tts_retry_success_after_429(tmp_path, capsys):
    """429/throttle retry: 2 fails then success, save called 3, log retry 1/4 captured."""
    out = tmp_path / "retry_success.mp3"
    voice = "en-US-AndrewNeural"

    save_calls = {"count": 0}

    class FakeCommunicate:
        def __init__(self, text, voice_arg):
            assert text == "hello world"
            assert voice_arg == voice

        async def save(self, path):
            save_calls["count"] += 1
            if save_calls["count"] <= 2:
                raise Exception("429 Too Many Requests")
            # success on 3rd
            Path(path).write_text("x" * 2048, encoding="utf-8")

    sleep_calls = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    async def _run():
        with patch("edge_tts.Communicate", FakeCommunicate):
            with patch("core.tts.asyncio.sleep", new=fake_sleep):
                await tts_text_to_mp3("hello world", str(out), voice, retries=5)

    asyncio.run(_run())

    assert save_calls["count"] == 3
    assert out.exists()
    assert out.read_text(encoding="utf-8") == "x" * 2048
    # sleep waits = min(20,2*1)=2, min(20,2*2)=4
    assert sleep_calls == [2, 4]
    captured = capsys.readouterr().out.lower()
    # spec says "retry 1/4 dla/for" — keep "for" but accept either case-insensitive
    assert "retry 1/4" in captured
    assert "retry 2/4" in captured
    # check filename in log (case-insensitive)
    assert "retry_success.mp3" in captured


def test_tts_exhaust_retries_raises(tmp_path, capsys):
    """Always raises → after 5 attempts raise RuntimeError with last_error chained."""
    out = tmp_path / "exhaust.mp3"
    voice = "en-US-AndrewNeural"

    class FakeCommunicateAlwaysFail:
        def __init__(self, text, voice_arg):
            pass

        async def save(self, path):
            raise Exception("503 throttle")

    sleep_calls = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    async def _run():
        with patch("edge_tts.Communicate", FakeCommunicateAlwaysFail):
            with patch("core.tts.asyncio.sleep", new=fake_sleep):
                with pytest.raises(RuntimeError, match=r"TTS failed after 5 attempts"):
                    await tts_text_to_mp3("hello", str(out), voice, retries=5)

    asyncio.run(_run())

    # 5 attempts → 4 sleeps (attempt 1..4 sleep, 5th raises)
    assert sleep_calls == [2, 4, 6, 8]
    assert len(sleep_calls) == 4
    captured = capsys.readouterr().out
    # 4 retry logs: 1/4,2/4,3/4,4/4
    for i in range(1, 5):
        assert f"retry {i}/4" in captured.lower() or f"retry {i}/4" in captured


def test_run_part_jobs_parallel_3_queue_order(tmp_path, capsys):
    """20 jobs parallel 3: all 20 done, progress 20/20, reading-order, workers 1,2,3 start first."""
    out_dir = tmp_path / "out_parallel"
    out_dir.mkdir()
    # Build 20 jobs via manual PartJob list in reading order ch40 p1..20 before ch41
    # Simpler: use single chapter 40 with 20 parts via "a"*70000
    chapters = [(40, "C40", "a" * 70000)]  # 70000/3500=20
    plans, jobs = build_generation_plan(chapters, str(out_dir), 3500)
    assert len(jobs) == 20, f"expected 20 jobs, got {len(jobs)}; chunks {len(plans[0].part_paths)}"
    # Ensure reading order: ch40 p1..20
    for i, j in enumerate(jobs, 1):
        assert j.chapter_number == 40
        assert j.part_number == i
        assert j.part_count == 20

    call_order = []

    async def fake_tts(text, output_path, voice, retries=5):
        call_order.append(Path(output_path).name)
        # Simulate file write to allow size_kb log and done log
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text("x" * 1024, encoding="utf-8")  # 1KB
        # small async yield to allow interleaving
        await asyncio.sleep(0)

    async def _run():
        with patch("core.tts.tts_text_to_mp3", new=fake_tts):
            await run_part_jobs(jobs, voice="en-US-AndrewNeural", parallel=3, retries=5)

    asyncio.run(_run())

    assert len(call_order) == 20
    # reading-order preserved at queue level — first three dispatched should be p1,p2,p3
    # Because workers start 1,2,3 concurrently, call_order first 3 should be p1,p2,p3 in some order but contains them
    assert set(call_order[:3]) == {"040_C40_part001.mp3", "040_C40_part002.mp3", "040_C40_part003.mp3"}
    # All jobs eventually called in order overall? With mocked immediate completion, order may be sequential due to async yield 0 but still global queue order ensures 4th starts only after one finishes.
    # Check that all expected names present
    expected_names = [f"040_C40_part{i:03d}.mp3" for i in range(1, 21)]
    assert sorted(call_order) == sorted(expected_names)
    # Progress logs
    out = capsys.readouterr().out
    assert "progress: 20/20" in out
    # Workers 1,2,3 should have started first — check logs contain worker 1: start, worker 2: start, worker 3: start
    assert "worker 1: start" in out
    assert "worker 2: start" in out
    assert "worker 3: start" in out
    # Verify no skip logs (all fresh)
    assert "skip" not in out.lower()


def test_run_part_jobs_skip_existing_parts(tmp_path, capsys):
    """Runtime skip guard: pre-create 1 file, mock tts not called for that job, skip log, progress counts skip."""
    out_dir = tmp_path / "out_skip"
    out_dir.mkdir()
    parts_dir = out_dir / "_parts"
    parts_dir.mkdir(parents=True, exist_ok=True)

    # Manually craft 2 jobs in same chapter, one already exists
    job1_path = parts_dir / "040_C40_part001.mp3"
    job2_path = parts_dir / "040_C40_part002.mp3"
    job1_path.write_text("x" * 2048, encoding="utf-8")
    # size will be len /1024 = 0 KB

    jobs = [
        PartJob(chapter_number=40, chapter_title="C40", part_number=1, part_count=2, text="chunk1", output_path=str(job1_path), is_final_chapter_file=False),
        PartJob(chapter_number=40, chapter_title="C40", part_number=2, part_count=2, text="chunk2", output_path=str(job2_path), is_final_chapter_file=False),
    ]

    tts_calls = []

    async def fake_tts(text, output_path, voice, retries=5):
        tts_calls.append(Path(output_path).name)
        Path(output_path).write_text("generated", encoding="utf-8")

    async def _run():
        with patch("core.tts.tts_text_to_mp3", new=fake_tts):
            await run_part_jobs(jobs, voice="en-US-AndrewNeural", parallel=2, retries=5)

    asyncio.run(_run())

    # Only job2 should have triggered TTS
    assert tts_calls == ["040_C40_part002.mp3"]
    assert job2_path.exists()
    out = capsys.readouterr().out
    # Skip log for job1
    assert "skip Chapter 040 part 001/002" in out
    assert "start Chapter 040 part 002/002" in out
    assert "done  Chapter 040 part 002/002" in out
    # Progress counts both: 1/2 and 2/2
    assert "progress: 1/2" in out
    assert "progress: 2/2" in out


def test_run_part_jobs_empty_jobs(capsys):
    """Empty jobs -> No TTS jobs message and no worker creation, no tts call."""
    async def _run():
        with patch("core.tts.tts_text_to_mp3") as mock_tts:
            await run_part_jobs([], voice="en-US-AndrewNeural", parallel=3, retries=5)
            mock_tts.assert_not_called()
    asyncio.run(_run())
    out = capsys.readouterr().out
    assert "No TTS jobs" in out


def test_retry_sleep_capped_at_20(tmp_path):
    """Sleep never >20s even with higher retries — min(20,2*attempt) capped."""
    out = tmp_path / "cap.mp3"
    voice = "en-US-AndrewNeural"

    class AlwaysFail:
        def __init__(self, text, voice_arg):
            pass

        async def save(self, path):
            raise Exception("fail")

    sleep_calls = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    async def _run():
        with patch("edge_tts.Communicate", AlwaysFail):
            with patch("core.tts.asyncio.sleep", new=fake_sleep):
                with pytest.raises(RuntimeError):
                    await tts_text_to_mp3("hello", str(out), voice, retries=15)

    asyncio.run(_run())

    # retries 15 -> sleeps for attempts 1..14: 2,4,6,8,10,12,14,16,18,20,20,20,20,20
    assert len(sleep_calls) == 14
    assert sleep_calls[:9] == [2, 4, 6, 8, 10, 12, 14, 16, 18]
    assert sleep_calls[9] == 20
    # All subsequent capped at 20
    assert all(s <= 20 for s in sleep_calls)
    assert sleep_calls[10:] == [20, 20, 20, 20]


def test_speak_delegation_parity(monkeypatch, tmp_path):
    """speak.py wrappers must delegate to core.tts — verify forwarding and signature preservation."""
    import speak as speak_mod
    import core.tts as core_mod

    # Check that speak wrappers exist and are coroutines
    assert asyncio.iscoroutinefunction(speak_mod.tts_text_to_mp3)
    assert asyncio.iscoroutinefunction(speak_mod.run_part_jobs)
    # Check that speak module exposes PartJob as same class (core identity)
    assert speak_mod.PartJob is core_mod.PartJob

    # Verify delegation: patch core and check speak wrapper calls it
    called = {}

    async def fake_core_tts(text, output_path, voice, retries=5, rate=None):
        called["tts"] = (text, output_path, voice, retries, rate)
        Path(output_path).write_text("ok", encoding="utf-8")

    async def fake_core_run(jobs, voice, parallel, retries, rate=None, adaptive=False, parallel_max=None, engine="edge", local_voice=None):
        called["run"] = (jobs, voice, parallel, retries, rate, adaptive, engine, local_voice)

    monkeypatch.setattr(core_mod, "tts_text_to_mp3", fake_core_tts)
    # Need to also patch the alias that speak imported at import time: _core_tts
    monkeypatch.setattr(speak_mod, "_core_tts", fake_core_tts, raising=False)
    monkeypatch.setattr(speak_mod, "_core_run", fake_core_run, raising=False)

    async def _run():
        # Test tts delegation
        out = tmp_path / "deleg.mp3"
        await speak_mod.tts_text_to_mp3("hi", str(out), "en-US-AriaNeural", retries=2)
        assert called["tts"] == ("hi", str(out), "en-US-AriaNeural", 2, None)
        await speak_mod.tts_text_to_mp3("hi", str(out), "en-US-AriaNeural", retries=2, rate="+10%")
        assert called["tts"] == ("hi", str(out), "en-US-AriaNeural", 2, "+10%")

        # Test run delegation with parallel propagation 1..6
        jobs = [
            PartJob(chapter_number=1, chapter_title="T", part_number=1, part_count=1, text="hi", output_path=str(tmp_path / "a.mp3"), is_final_chapter_file=True)
        ]
        await speak_mod.run_part_jobs(jobs, voice="en-US-AriaNeural", parallel=3, retries=5, rate="+25%")
        assert called["run"][2] == 3  # parallel
        assert called["run"][1] == "en-US-AriaNeural"
        assert called["run"][4] == "+25%"  # rate forwarded
        assert called["run"][5] is True  # adaptive enabled by the wrapper
        assert called["run"][6] == "edge"  # engine default
        await speak_mod.run_part_jobs(
            jobs, voice="en-US-AriaNeural", parallel=3, retries=5, engine="local", local_voice="pl_PL-darkman-medium"
        )
        assert called["run"][6] == "local"
        assert called["run"][7] == "pl_PL-darkman-medium"

    asyncio.run(_run())


def test_run_part_jobs_parallel_2_vs_3(tmp_path):
    """Both parallel 2 and 3 work; parallel 1 also valid (sequential)."""
    out_dir2 = tmp_path / "out2"
    out_dir3 = tmp_path / "out3"
    out_dir2.mkdir()
    out_dir3.mkdir()

    chapters = [(1, "T", "a" * 4000)]  # 2 parts

    _, jobs2 = build_generation_plan(chapters, str(out_dir2), 3500)
    _, jobs3 = build_generation_plan(chapters, str(out_dir3), 3500)

    async def fake_tts(text, output_path, voice, retries=5):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text("x", encoding="utf-8")

    async def _run():
        with patch("core.tts.tts_text_to_mp3", new=fake_tts):
            await run_part_jobs(jobs2, voice="v", parallel=2, retries=5)
            await run_part_jobs(jobs3, voice="v", parallel=3, retries=5)
            # also parallel=1 sequential
            out_dir1 = tmp_path / "out1"
            out_dir1.mkdir()
            _, jobs1 = build_generation_plan(chapters, str(out_dir1), 3500)
            await run_part_jobs(jobs1, voice="v", parallel=1, retries=5)

    asyncio.run(_run())

    # All succeeded without exception
    assert True


def test_run_part_jobs_max_concurrency_and_exact_order(tmp_path, capsys):
    """Verify max concurrency <= parallel and exact reading-order for 20 jobs."""
    out_dir = tmp_path / "out_conc"
    out_dir.mkdir()
    chapters = [(40, "C40", "a" * 70000)]  # 20 parts
    _, jobs = build_generation_plan(chapters, str(out_dir), 3500)
    assert len(jobs) == 20
    expected = [f"040_C40_part{i:03d}.mp3" for i in range(1, 21)]

    concurrent = {"cur": 0, "max": 0}
    call_order = []
    lock = asyncio.Lock()

    async def fake_tts(text, output_path, voice, retries=5):
        async with lock:
            concurrent["cur"] += 1
            concurrent["max"] = max(concurrent["max"], concurrent["cur"])
        call_order.append(Path(output_path).name)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text("x" * 1024, encoding="utf-8")
        await asyncio.sleep(0.01)
        async with lock:
            concurrent["cur"] -= 1

    async def _run():
        with patch("core.tts.tts_text_to_mp3", new=fake_tts):
            await run_part_jobs(jobs, voice="v", parallel=3, retries=5)

    asyncio.run(_run())

    assert call_order == expected, f"order mismatch {call_order[:5]}"
    assert concurrent["max"] <= 3
    assert concurrent["max"] == 3  # when jobs >= parallel, max should hit parallel
    out = capsys.readouterr().out
    assert "progress: 20/20" in out


def test_run_part_jobs_propagates_tts_failure(tmp_path, capsys):
    """Middle job failure after exhausting retries must propagate and cancel remaining."""
    out_dir = tmp_path / "out_fail"
    out_dir.mkdir()
    chapters = [(40, "C40", "a" * 8000)]  # 3 parts: 3500,3500,1000
    _, jobs = build_generation_plan(chapters, str(out_dir), 3500)
    assert len(jobs) == 3

    call_log = []

    async def fake_tts(text, output_path, voice, retries=5):
        name = Path(output_path).name
        call_log.append(name)
        if "part002" in name:
            raise RuntimeError("TTS failed after 5 attempts")
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text("ok", encoding="utf-8")
        await asyncio.sleep(0.01)

    async def _run():
        with patch("core.tts.tts_text_to_mp3", new=fake_tts):
            with pytest.raises(RuntimeError, match="TTS failed"):
                await run_part_jobs(jobs, voice="v", parallel=1, retries=5)

    asyncio.run(_run())

    # with parallel 1, jobs sequential p1, p2(fail), p3 never started
    assert "040_C40_part001.mp3" in call_log
    assert "040_C40_part002.mp3" in call_log
    assert "040_C40_part003.mp3" not in call_log
    # progress should not reach 3/3
    out = capsys.readouterr().out
    assert "progress: 3/3" not in out


# ---------------------------------------------------------------------------
# Story 3.3 — FFmpeg merge per-chapter + single M4B z markerami
# ---------------------------------------------------------------------------


def test_ffmpeg_available_true():
    with patch("core.tts.shutil.which", return_value="/usr/bin/ffmpeg"):
        assert ffmpeg_available() is True


def test_ffmpeg_available_false():
    with patch("core.tts.shutil.which", return_value=None):
        assert ffmpeg_available() is False


def test_ffprobe_available_true():
    with patch("core.tts.shutil.which", side_effect=lambda x: "/usr/bin/" + x if x == "ffprobe" else None):
        assert ffprobe_available() is True


def test_ffprobe_available_false():
    with patch("core.tts.shutil.which", return_value=None):
        assert ffprobe_available() is False


def test_concat_mp3_files_success(tmp_path):
    output = tmp_path / "040_C40.mp3"
    # Create dummy input parts
    p1 = tmp_path / "040_C40_part001.mp3"
    p2 = tmp_path / "040_C40_part002.mp3"
    p1.write_bytes(b"fake1")
    p2.write_bytes(b"fake2")
    input_paths = [str(p1), str(p2)]

    concat_file = str(output.with_suffix(".concat.txt"))
    tmp_output = str(output) + ".tmp"

    captured = {}

    def fake_run(args, check=True, stdout=None, stderr=None, **kwargs):
        captured["args"] = args
        # verify concat file content before it gets removed
        assert os.path.exists(concat_file)
        content = Path(concat_file).read_text(encoding="utf-8")
        # spec: file '{safe}' where safe = abspath replace
        for p in input_paths:
            safe = os.path.abspath(p).replace("\\", "/").replace("'", "\\'")
            assert f"file '{safe}'\n" in content
        # simulate ffmpeg creating the temp output (atomic publish on success)
        Path(args[-1]).write_bytes(b"merged")
        # .tmp output needs an explicit muxer (ffmpeg cannot infer from .tmp)
        assert args[-3:-1] == ["-f", "mp3"]
        return MagicMock(returncode=0)

    with patch("core.tts.shutil.which", return_value="/usr/bin/ffmpeg"):
        with patch("core.tts.subprocess.run", side_effect=fake_run) as mock_run:
            concat_mp3_files(input_paths, str(output))

    assert captured["args"] == ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_file, "-c", "copy", "-f", "mp3", tmp_output]
    mock_run.assert_called_once()
    # concat_file cleaned up, temp published atomically, no stray .tmp left
    assert not os.path.exists(concat_file)
    assert not os.path.exists(tmp_output)
    assert output.exists()
    assert output.read_bytes() == b"merged"


def test_concat_mp3_files_no_ffmpeg_raises(tmp_path):
    output = tmp_path / "040_C40.mp3"
    with patch("core.tts.shutil.which", return_value=None):
        with pytest.raises(RuntimeError, match="ffmpeg is not available"):
            concat_mp3_files([str(tmp_path / "a.mp3")], str(output))


def test_get_duration_ms_via_ffprobe(tmp_path):
    dummy = tmp_path / "dummy.mp3"
    dummy.write_bytes(b"x")
    # Happy 12.345 -> 12345
    with patch("core.tts.shutil.which", return_value="/usr/bin/ffprobe"):
        mock_result = MagicMock(stdout="12.345\n")
        with patch("core.tts.subprocess.run", return_value=mock_result) as mock_run:
            assert get_duration_ms(str(dummy)) == 12345
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert args[0] == "ffprobe"
            assert "-show_entries" in args
            assert "format=duration" in args
    # unparsable output -> the probe FAILED (-1), not "no audio" (0)
    with patch("core.tts.shutil.which", return_value="/usr/bin/ffprobe"):
        mock_result2 = MagicMock(stdout="not_a_number\n")
        with patch("core.tts.subprocess.run", return_value=mock_result2):
            assert get_duration_ms(str(dummy)) == -1
    # no ffprobe at all -> probe failed (-1), no subprocess call
    with patch("core.tts.shutil.which", return_value=None):
        with patch("core.tts.subprocess.run") as mock_run2:
            assert get_duration_ms(str(dummy)) == -1
            mock_run2.assert_not_called()


def test_escape_ffmeta():
    # spec: re.sub r"([=;#\\])" r"\\\1" + replace "\n" "\\n"
    # "a=b;c#d\e" + newline + "f"
    assert escape_ffmeta("a=b;c#d\\e\nf") == "a\\=b\\;c\\#d\\\\e\\nf"
    # Direct checks
    assert escape_ffmeta("title=My;Book#1\\") == "title\\=My\\;Book\\#1\\\\"
    assert escape_ffmeta("line1\nline2") == "line1\\nline2"
    assert escape_ffmeta("a=b") == r"a\=b"
    assert escape_ffmeta("a;b#c\\d") == r"a\;b\#c\\d"


def test_finalize_chapter_audio_merges(tmp_path, capsys):
    # Happy per-chapter merge: _parts/040_C40_part001.mp3 etc, 040_C40.mp3 missing, ffmpeg True, keep_parts False
    out = tmp_path / "out_merges"
    out.mkdir()
    parts_dir = out / "_parts"
    parts_dir.mkdir()
    p1 = parts_dir / "040_C40_part001.mp3"
    p2 = parts_dir / "040_C40_part002.mp3"
    p1.write_bytes(b"p1")
    p2.write_bytes(b"p2")
    chapter_mp3 = out / "040_C40.mp3"
    assert not chapter_mp3.exists()
    plan = ChapterPlan(
        chapter_number=40,
        title="C40",
        chapter_mp3=str(chapter_mp3),
        part_paths=[str(p1), str(p2)],
        marker_entries_if_unmerged=[(40, "C40 - part 1", str(p1)), (40, "C40 - part 2", str(p2))],
    )

    def fake_concat(input_paths, output_path):
        # simulate ffmpeg merge creating file
        Path(output_path).write_bytes(b"merged40")

    with patch("core.tts.ffmpeg_available", return_value=True):
        with patch("core.tts.concat_mp3_files", side_effect=fake_concat) as mock_concat:
            entries = finalize_chapter_audio([plan], keep_parts=False)

    mock_concat.assert_called_once_with([str(p1), str(p2)], str(chapter_mp3))
    assert entries == [(40, "C40", str(chapter_mp3))]
    assert chapter_mp3.exists()
    # parts removed
    assert not p1.exists()
    assert not p2.exists()
    # _parts dir removed if empty
    assert not parts_dir.exists()
    out_text = capsys.readouterr().out
    assert "merging 2 part(s)" in out_text


def test_finalize_no_ffmpeg_keeps_parts(tmp_path, capsys):
    out = tmp_path / "out_no_ffmpeg"
    out.mkdir()
    parts_dir = out / "_parts"
    parts_dir.mkdir()
    p1 = parts_dir / "040_C40_part001.mp3"
    p2 = parts_dir / "040_C40_part002.mp3"
    p1.write_bytes(b"p1")
    p2.write_bytes(b"p2")
    chapter_mp3 = out / "040_C40.mp3"
    plan = ChapterPlan(40, "C40", str(chapter_mp3), [str(p1), str(p2)], [(40, "C40 - part 1", str(p1)), (40, "C40 - part 2", str(p2))])

    with patch("core.tts.ffmpeg_available", return_value=False):
        with patch("core.tts.concat_mp3_files") as mock_concat:
            entries = finalize_chapter_audio([plan], keep_parts=False)

    mock_concat.assert_not_called()
    # should extend marker_entries_if_unmerged (keep _parts files)
    assert entries == [(40, "C40 - part 1", str(p1)), (40, "C40 - part 2", str(p2))]
    assert p1.exists() and p2.exists()
    assert "ffmpeg unavailable" in capsys.readouterr().out


def test_finalize_missing_parts_warning(tmp_path, capsys):
    out = tmp_path / "out_missing"
    out.mkdir()
    parts_dir = out / "_parts"
    parts_dir.mkdir()
    p1 = parts_dir / "040_C40_part001.mp3"
    p2 = parts_dir / "040_C40_part002.mp3"
    p1.write_bytes(b"p1")
    # p2 missing
    chapter_mp3 = out / "040_C40.mp3"
    plan = ChapterPlan(40, "C40", str(chapter_mp3), [str(p1), str(p2)], [(40, "C40 - part 1", str(p1)), (40, "C40 - part 2", str(p2))])

    with patch("core.tts.ffmpeg_available", return_value=True):
        with patch("core.tts.concat_mp3_files") as mock_concat:
            entries = finalize_chapter_audio([plan], keep_parts=False)

    mock_concat.assert_not_called()
    # only existing marker entries
    assert entries == [(40, "C40 - part 1", str(p1))]
    assert "missing part files" in capsys.readouterr().out.lower()


def test_finalize_already_merged_skip(tmp_path, capsys):
    out = tmp_path / "out_reuse"
    out.mkdir()
    parts_dir = out / "_parts"
    parts_dir.mkdir()
    p1 = parts_dir / "040_C40_part001.mp3"
    p2 = parts_dir / "040_C40_part002.mp3"
    p1.write_bytes(b"p1")
    p2.write_bytes(b"p2")
    chapter_mp3 = out / "040_C40.mp3"
    chapter_mp3.write_bytes(b"already")
    plan = ChapterPlan(40, "C40", str(chapter_mp3), [str(p1), str(p2)], [(40, "C40 - part 1", str(p1)), (40, "C40 - part 2", str(p2))])

    with patch("core.tts.ffmpeg_available", return_value=True):
        with patch("core.tts.concat_mp3_files") as mock_concat:
            entries = finalize_chapter_audio([plan], keep_parts=False)

    mock_concat.assert_not_called()
    assert entries == [(40, "C40", str(chapter_mp3))]
    assert "existing merged file reused" in capsys.readouterr().out


def test_finalize_keep_parts_true(tmp_path):
    out = tmp_path / "out_keep"
    out.mkdir()
    parts_dir = out / "_parts"
    parts_dir.mkdir()
    p1 = parts_dir / "040_C40_part001.mp3"
    p2 = parts_dir / "040_C40_part002.mp3"
    p1.write_bytes(b"p1")
    p2.write_bytes(b"p2")
    chapter_mp3 = out / "040_C40.mp3"
    plan = ChapterPlan(40, "C40", str(chapter_mp3), [str(p1), str(p2)], [(40, "C40 - part 1", str(p1)), (40, "C40 - part 2", str(p2))])

    def fake_concat(input_paths, output_path):
        Path(output_path).write_bytes(b"merged")

    with patch("core.tts.ffmpeg_available", return_value=True):
        with patch("core.tts.concat_mp3_files", side_effect=fake_concat):
            entries = finalize_chapter_audio([plan], keep_parts=True)

    assert entries == [(40, "C40", str(chapter_mp3))]
    # parts kept
    assert p1.exists() and p2.exists()
    assert parts_dir.exists()


def test_finalize_single_chunk(tmp_path, capsys):
    out = tmp_path / "out_single"
    out.mkdir()
    chapter_mp3 = out / "005_T.mp3"
    chapter_mp3.write_bytes(b"single")
    plan = ChapterPlan(5, "T", str(chapter_mp3), [str(chapter_mp3)], [(5, "T", str(chapter_mp3))])

    with patch("core.tts.ffmpeg_available", return_value=True):
        entries = finalize_chapter_audio([plan], keep_parts=False)
    assert entries == [(5, "T", str(chapter_mp3))]


def test_finalize_empty_plans():
    with patch("core.tts.ffmpeg_available", return_value=True):
        assert finalize_chapter_audio([], keep_parts=False) == []


def test_build_m4b_creates_with_markers(tmp_path, capsys):
    out = tmp_path / "out_m4b"
    out.mkdir()
    a = out / "001_Ch1.mp3"
    b = out / "002_Ch2.mp3"
    a.write_bytes(b"a")
    b.write_bytes(b"b")
    audio_entries = [(1, "Ch1", str(a)), (2, "Ch2", str(b))]
    book_title = "book_chapters_001_to_002"

    captured = {}

    def fake_run(args, check=True, **kwargs):
        captured["args"] = args
        # Verify concat file before removal: it should exist and contain safe paths
        concat_path = out / "_concat.txt"
        metadata_path = out / "_metadata.txt"
        assert concat_path.exists()
        assert metadata_path.exists()
        concat_content = concat_path.read_text(encoding="utf-8")
        for _, _, p in audio_entries:
            safe = os.path.abspath(p).replace("\\", "/").replace("'", "'\\''")
            assert f"file '{safe}'\n" in concat_content
        meta = metadata_path.read_text(encoding="utf-8")
        assert ";FFMETADATA1" in meta
        assert f"title={escape_ffmeta(book_title)}" in meta
        assert "TIMEBASE=1/1000" in meta
        # duration 1000 each -> START 0 END 1000, START 1000 END 2000
        assert "START=0" in meta
        assert "END=1000" in meta
        assert "START=1000" in meta
        assert "END=2000" in meta
        # chapter titles escaped
        assert "title=001 - Ch1" in meta
        assert "title=002 - Ch2" in meta
        # simulate ffmpeg creating output (atomic publish: ffmpeg writes the
        # .tmp sidecar, build_m4b moves it into place afterwards)
        Path(args[-1]).write_bytes(b"m4bcontent" * 1024)
        return MagicMock(returncode=0)

    with patch("core.tts.ffmpeg_available", return_value=True):
        with patch("core.tts.ffprobe_available", return_value=True):
            with patch("core.tts.probe_duration_ms", side_effect=[1000, 1000]):
                with patch("core.tts.subprocess.run", side_effect=fake_run) as mock_run:
                    build_m4b(str(out), audio_entries, book_title, ext="m4b")

    mock_run.assert_called_once()
    args = captured["args"]
    assert args[0] == "ffmpeg"
    assert "-y" in args and "-f" in args and "concat" in args
    assert "-map_metadata" in args and "1" in args
    assert "-c:a" in args and "aac" in args and "-b:a" in args and "32k" in args
    expected_out = str(out / f"{book_title}.m4b")
    # ffmpeg writes the sidecar; the final name is published atomically
    assert args[-1] == expected_out + ".tmp"
    # temps removed
    assert not (out / "_concat.txt").exists()
    assert not (out / "_metadata.txt").exists()
    assert not (out / f"{book_title}.m4b.tmp").exists()
    assert (out / f"{book_title}.m4b").exists()
    assert "M4B saved" in capsys.readouterr().out


def test_build_m4b_bitrate_passthrough_and_validation(tmp_path):
    import time

    from core.tts import _estimate_m4b_size, _parse_audio_bitrate, build_m4b

    assert _parse_audio_bitrate(None) == "32k"
    assert _parse_audio_bitrate("") == "32k"
    assert _parse_audio_bitrate("48K") == "48k"
    assert _parse_audio_bitrate(" 64k ") == "64k"
    for bad in ("ogg", "0k", "8k", "999k", 123):
        try:
            _parse_audio_bitrate(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected VALUE_ERROR for {bad!r}")

    # estimate scales with bitrate*duration
    assert _estimate_m4b_size("64k", 60_000) > _estimate_m4b_size("32k", 60_000) > 0

    out = tmp_path / "out_br"
    out.mkdir()
    a = out / "001.mp3"
    a.write_bytes(b"a")
    entries = [(1, "Ch1", str(a))]
    captured = {}

    def fake_run(args, check=True, **kwargs):
        captured["args"] = args
        Path(args[-1]).write_bytes(b"x" * 100)
        return MagicMock(returncode=0)

    with patch("core.tts.ffmpeg_available", return_value=True):
        with patch("core.tts.ffprobe_available", return_value=True):
            with patch("core.tts.probe_duration_ms", return_value=1000):
                with patch("core.tts.subprocess.run", side_effect=fake_run):
                    build_m4b(str(out), entries, "book", ext="m4b", bitrate="48k")
    assert "-b:a" in captured["args"] and "48k" in captured["args"]

    try:
        build_m4b(str(out), entries, "book", ext="m4b", bitrate="ogg")
    except ValueError as e:
        assert "bitrate" in str(e)
    else:
        raise AssertionError("expected VALUE_ERROR for bad bitrate")


def test_build_m4b_progress_poll_reports_size(tmp_path):
    import time

    from core.tts import build_m4b

    out = tmp_path / "out_prog"
    out.mkdir()
    a = out / "001.mp3"
    a.write_bytes(b"a")
    entries = [(1, "Ch1", str(a))]
    seen = []

    def fake_slow_run(args, check=True, **kwargs):
        # simulate a 4.5s encode with a growing output file
        target = Path(args[-1])
        for _ in range(9):
            with open(target, "ab") as f:
                f.write(b"x" * 50000)
            time.sleep(0.5)
        return MagicMock(returncode=0)

    with patch("core.tts.ffmpeg_available", return_value=True):
        with patch("core.tts.ffprobe_available", return_value=True):
            with patch("core.tts.probe_duration_ms", return_value=60000):
                with patch("core.tts.subprocess.run", side_effect=fake_slow_run):
                    build_m4b(str(out), entries, "book", ext="m4b",
                              on_progress=lambda d, t: seen.append((d, t)))
    assert seen, "expected at least one progress callback during slow encode"
    assert all(0 <= d <= t and t > 0 for d, t in seen)
    assert seen[-1][0] <= seen[-1][1]


def test_build_m4b_probe_reports_per_file(tmp_path):
    from core.tts import build_m4b

    out = tmp_path / "out_probe"
    out.mkdir()
    a = out / "001.mp3"
    b = out / "002.mp3"
    a.write_bytes(b"a")
    b.write_bytes(b"b")
    entries = [(1, "Ch1", str(a)), (2, "Ch2", str(b))]
    probed = []

    def fake_run(args, check=True, **kwargs):
        Path(args[-1]).write_bytes(b"z")
        return MagicMock(returncode=0)

    with patch("core.tts.ffmpeg_available", return_value=True):
        with patch("core.tts.ffprobe_available", return_value=True):
            with patch("core.tts.probe_duration_ms", return_value=1000):
                with patch("core.tts.subprocess.run", side_effect=fake_run):
                    build_m4b(str(out), entries, "book", ext="m4b",
                              on_probe=lambda d, t: probed.append((d, t)))
    assert [(d, t) for d, t in probed] == [(1, 2), (2, 2)]


def test_build_m4b_no_ffmpeg_skip(tmp_path, capsys):
    out = tmp_path / "out_nom4b"
    out.mkdir()
    with patch("core.tts.ffmpeg_available", return_value=False):
        build_m4b(str(out), [(1, "Ch1", str(out / "a.mp3"))], "book", ext="m4b")
    out_txt = capsys.readouterr().out
    assert "ffmpeg not found" in out_txt.lower()
    assert not (out / "book.m4b").exists()


def test_build_m4b_no_ffprobe_skip(tmp_path, capsys):
    out = tmp_path / "out_noprobe"
    out.mkdir()
    a = out / "001.mp3"
    a.write_bytes(b"x")
    with patch("core.tts.ffmpeg_available", return_value=True):
        with patch("core.tts.ffprobe_available", return_value=False):
            build_m4b(str(out), [(1, "Ch1", str(a))], "book", ext="m4b")
    assert "ffprobe not found" in capsys.readouterr().out.lower()
    assert not (out / "book.m4b").exists()


def test_build_m4b_ffprobe_duration_zero(tmp_path, capsys):
    # a chapter whose duration cannot be determined must ABORT the packaging:
    # writing START=0/END=0 markers shifts every later chapter boundary
    out = tmp_path / "out_zero"
    out.mkdir()
    a = out / "001.mp3"
    a.write_bytes(b"x")
    audio_entries = [(1, "Ch1", str(a))]

    with patch("core.tts.ffmpeg_available", return_value=True):
        with patch("core.tts.ffprobe_available", return_value=True):
            with patch("core.tts.probe_duration_ms", return_value=0):
                with patch("core.tts.subprocess.run"):
                    try:
                        build_m4b(str(out), audio_entries, "book", ext="m4b")
                    except RuntimeError as e:
                        assert "duration" in str(e)
                    else:
                        raise AssertionError("expected a RuntimeError for a zero-duration chapter")
    # nothing was published
    assert not (out / "book.m4b").exists()


def test_build_m4b_ffprobe_failure_aborts(tmp_path):
    # a failed probe is not a zero-length file — it must abort too
    out = tmp_path / "out_probe_fail"
    out.mkdir()
    a = out / "001.mp3"
    a.write_bytes(b"x")
    with patch("core.tts.ffmpeg_available", return_value=True):
        with patch("core.tts.ffprobe_available", return_value=True):
            with patch("core.tts.probe_duration_ms", return_value=None):
                with patch("core.tts.subprocess.run"):
                    try:
                        build_m4b(str(out), [(1, "Ch1", str(a))], "book", ext="m4b")
                    except RuntimeError as e:
                        assert "duration" in str(e)
                    else:
                        raise AssertionError("expected a RuntimeError when ffprobe fails")
    assert not (out / "book.m4b").exists()


def test_build_m4b_empty_entries_rejected(tmp_path):
    from core.tts import build_m4b

    out = tmp_path / "out_empty"
    out.mkdir()
    try:
        build_m4b(str(out), [], "book", ext="m4b")
    except ValueError as e:
        assert "no audio entries" in str(e)
    else:
        raise AssertionError("expected a ValueError for an empty chapter list")


def test_speak_delegation_parity_merge(monkeypatch, tmp_path):
    """speak.py wrappers must delegate to core.tts for 3.3 merge functions."""
    import speak as speak_mod
    import core.tts as core_mod

    assert speak_mod.ffmpeg_available is not None
    assert speak_mod.ffprobe_available is not None
    assert speak_mod.concat_mp3_files is not None
    assert speak_mod.get_duration_ms is not None
    assert speak_mod.escape_ffmeta is not None
    assert speak_mod.finalize_chapter_audio is not None
    assert speak_mod.build_m4b is not None

    # Verify delegation: patch core and check speak wrapper calls it
    called = {}

    def fake_ffmpeg():
        called["ffmpeg"] = True
        return True

    def fake_ffprobe():
        called["ffprobe"] = True
        return True

    def fake_concat(paths, out):
        called["concat"] = (paths, out)

    def fake_dur(p):
        called["dur"] = p
        return 123

    def fake_escape(s):
        called["escape"] = s
        return "esc_" + s

    def fake_finalize(plans, keep, **kw):
        called["finalize"] = (plans, keep)
        return [(1, "T", "/tmp/a.mp3")]

    def fake_m4b(out_dir, entries, title, ext="m4b", **kwargs):
        called["m4b"] = (out_dir, entries, title, ext, kwargs.get("bitrate"))

    monkeypatch.setattr(core_mod, "ffmpeg_available", fake_ffmpeg)
    monkeypatch.setattr(core_mod, "ffprobe_available", fake_ffprobe)
    monkeypatch.setattr(core_mod, "concat_mp3_files", fake_concat)
    monkeypatch.setattr(core_mod, "get_duration_ms", fake_dur)
    monkeypatch.setattr(core_mod, "escape_ffmeta", fake_escape)
    monkeypatch.setattr(core_mod, "finalize_chapter_audio", fake_finalize)
    monkeypatch.setattr(core_mod, "build_m4b", fake_m4b)
    # Also patch the alias that speak imported at import time
    monkeypatch.setattr(speak_mod, "_core_ffmpeg", fake_ffmpeg, raising=False)
    monkeypatch.setattr(speak_mod, "_core_ffprobe", fake_ffprobe, raising=False)
    monkeypatch.setattr(speak_mod, "_core_concat", fake_concat, raising=False)
    monkeypatch.setattr(speak_mod, "_core_dur", fake_dur, raising=False)
    monkeypatch.setattr(speak_mod, "_core_escape", fake_escape, raising=False)
    monkeypatch.setattr(speak_mod, "_core_finalize", fake_finalize, raising=False)
    monkeypatch.setattr(speak_mod, "_core_m4b", fake_m4b, raising=False)

    assert speak_mod.ffmpeg_available() is True
    assert called["ffmpeg"] is True
    assert speak_mod.ffprobe_available() is True
    assert speak_mod.get_duration_ms("/tmp/x.mp3") == 123
    assert speak_mod.escape_ffmeta("hi") == "esc_hi"
    assert speak_mod.finalize_chapter_audio([], False) == [(1, "T", "/tmp/a.mp3")]
    speak_mod.concat_mp3_files(["a"], "b")
    assert called["concat"] == (["a"], "b")
    speak_mod.build_m4b("out", [], "title")
    assert called["m4b"][0] == "out"


# ---------------------------------------------------------------------------
# Review 2026-08-29 — patch verification for blind/edge/verification gaps
# ---------------------------------------------------------------------------


def test_concat_mp3_files_empty_raises(tmp_path):
    out = tmp_path / "out.mp3"
    with patch("core.tts.shutil.which", return_value="/usr/bin/ffmpeg"):
        with pytest.raises(ValueError, match="no input paths"):
            concat_mp3_files([], str(out))
        with pytest.raises(ValueError):
            concat_mp3_files([], str(out))


def test_concat_mp3_files_parent_makedirs(tmp_path):
    # output in non-existent subdir
    out = tmp_path / "newdir" / "sub" / "040_C40.mp3"
    p1 = tmp_path / "p1.mp3"
    p1.write_bytes(b"x")
    assert not out.parent.exists()

    def fake_run(args, check=True, stdout=None, stderr=None, **kwargs):
        # ffmpeg writes the temp target; the function publishes it atomically
        Path(args[-1]).write_bytes(b"merged")
        return MagicMock(returncode=0)

    with patch("core.tts.shutil.which", return_value="/usr/bin/ffmpeg"):
        with patch("core.tts.subprocess.run", side_effect=fake_run):
            concat_mp3_files([str(p1)], str(out))
    assert out.exists()
    assert out.parent.exists()
    assert not (tmp_path / "newdir" / "sub" / "040_C40.mp3.tmp").exists()


def test_get_duration_ms_broad_exceptions(tmp_path):
    dummy = tmp_path / "dummy.mp3"
    dummy.write_bytes(b"x")
    # every probe failure reports -1 ("unknown"), never 0 ("probed, no audio")
    # Timeout -> -1
    with patch("core.tts.shutil.which", return_value="/usr/bin/ffprobe"):
        with patch("core.tts.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="ffprobe", timeout=15)):
            assert get_duration_ms(str(dummy)) == -1
    # FileNotFoundError race -> -1
    with patch("core.tts.shutil.which", return_value="/usr/bin/ffprobe"):
        with patch("core.tts.subprocess.run", side_effect=FileNotFoundError()):
            assert get_duration_ms(str(dummy)) == -1
    # Non-zero returncode -> -1
    with patch("core.tts.shutil.which", return_value="/usr/bin/ffprobe"):
        mock_res = MagicMock(stdout="12.3\n", returncode=1)
        with patch("core.tts.subprocess.run", return_value=mock_res):
            assert get_duration_ms(str(dummy)) == -1
    # inf Overflow -> -1
    with patch("core.tts.shutil.which", return_value="/usr/bin/ffprobe"):
        mock_res2 = MagicMock(stdout="inf\n", returncode=0)
        with patch("core.tts.subprocess.run", return_value=mock_res2):
            assert get_duration_ms(str(dummy)) == -1
    # None stdout -> -1 (probe could not tell)
    with patch("core.tts.shutil.which", return_value="/usr/bin/ffprobe"):
        mock_res3 = MagicMock(stdout=None, returncode=0)
        with patch("core.tts.subprocess.run", return_value=mock_res3):
            assert get_duration_ms(str(dummy)) == -1
    # empty stdout -> -1 (probe could not tell)
    with patch("core.tts.shutil.which", return_value="/usr/bin/ffprobe"):
        mock_res4 = MagicMock(stdout="   \n", returncode=0)
        with patch("core.tts.subprocess.run", return_value=mock_res4):
            assert get_duration_ms(str(dummy)) == -1


def test_escape_ffmeta_defensive(tmp_path):
    assert escape_ffmeta(None) == ""
    assert escape_ffmeta(123) == "123"
    assert escape_ffmeta("a\r\nb") == "a\\r\\nb"


def test_finalize_single_chunk_missing(tmp_path, capsys):
    out = tmp_path / "out_single_missing"
    out.mkdir()
    chapter_mp3 = out / "005_T.mp3"
    assert not chapter_mp3.exists()
    plan = ChapterPlan(5, "T", str(chapter_mp3), [str(chapter_mp3)], [(5, "T", str(chapter_mp3))])
    with patch("core.tts.ffmpeg_available", return_value=True):
        entries = finalize_chapter_audio([plan], keep_parts=False)
    assert entries == []
    assert "missing chapter MP3" in capsys.readouterr().out


def test_finalize_sorting_out_of_order(tmp_path):
    out = tmp_path / "out_sort"
    out.mkdir()
    # create two merged files
    a = out / "001_A.mp3"
    b = out / "002_B.mp3"
    a.write_bytes(b"a")
    b.write_bytes(b"b")
    # plans in reverse order
    plan2 = ChapterPlan(2, "B", str(b), [str(b)], [(2, "B", str(b))])
    plan1 = ChapterPlan(1, "A", str(a), [str(a)], [(1, "A", str(a))])
    with patch("core.tts.ffmpeg_available", return_value=True):
        entries = finalize_chapter_audio([plan2, plan1], keep_parts=False)
    assert entries[0][0] == 1
    assert entries[1][0] == 2
    assert entries[0][2] == str(a)
    assert entries[1][2] == str(b)


def test_finalize_zero_byte_remerge(tmp_path, capsys):
    out = tmp_path / "out_zero"
    out.mkdir()
    parts_dir = out / "_parts"
    parts_dir.mkdir()
    p1 = parts_dir / "040_C40_part001.mp3"
    p2 = parts_dir / "040_C40_part002.mp3"
    p1.write_bytes(b"p1")
    p2.write_bytes(b"p2")
    chapter_mp3 = out / "040_C40.mp3"
    chapter_mp3.write_bytes(b"")  # zero-byte corrupt
    plan = ChapterPlan(40, "C40", str(chapter_mp3), [str(p1), str(p2)], [(40, "C40 - part 1", str(p1)), (40, "C40 - part 2", str(p2))])

    def fake_concat(paths, out_path):
        Path(out_path).write_bytes(b"remerged")

    with patch("core.tts.ffmpeg_available", return_value=True):
        with patch("core.tts.concat_mp3_files", side_effect=fake_concat) as mock_concat:
            entries = finalize_chapter_audio([plan], keep_parts=False)
    mock_concat.assert_called_once()
    assert entries == [(40, "C40", str(chapter_mp3))]
    assert chapter_mp3.read_bytes() == b"remerged"


def test_finalize_exact_parts_name_no_false_positive(tmp_path):
    out = tmp_path / "out_exact"
    out.mkdir()
    # create fake dir that contains _parts substring but not exact
    fake_dir = out / "my_parts_backup"
    fake_dir.mkdir()
    p1 = fake_dir / "040_C40_part001.mp3"
    p1.write_bytes(b"p1")
    # but plan uses that path (unrealistic but test filter)
    chapter_mp3 = out / "040_C40.mp3"

    def fake_concat(paths, out_path):
        Path(out_path).write_bytes(b"merged")

    plan = ChapterPlan(40, "C40", str(chapter_mp3), [str(p1)], [(40, "C40 - part 1", str(p1))])
    # need two parts to trigger merge path; create second in _parts
    parts_dir = out / "_parts"
    parts_dir.mkdir()
    p2 = parts_dir / "040_C40_part002.mp3"
    p2.write_bytes(b"p2")
    plan2 = ChapterPlan(40, "C40", str(chapter_mp3), [str(p1), str(p2)], [(40, "C40 - part 1", str(p1)), (40, "C40 - part 2", str(p2))])
    # use only plan2
    with patch("core.tts.ffmpeg_available", return_value=True):
        with patch("core.tts.concat_mp3_files", side_effect=fake_concat):
            finalize_chapter_audio([plan2], keep_parts=False)
    # my_parts_backup should still exist (not removed)
    assert fake_dir.exists()
    # _parts should be removed if empty after keep_parts False and successful merge (p2 removed but p1 in fake_dir not removed)
    # exact test: _parts dir still exists because p1 not in _parts? Actually p2 removed, _parts empty -> should be removed
    # So check fake_dir not removed proves filter works
    assert fake_dir.exists()


def test_finalize_concat_failure_fallback(tmp_path, capsys):
    out = tmp_path / "out_fail_fallback"
    out.mkdir()
    parts_dir = out / "_parts"
    parts_dir.mkdir()
    p1 = parts_dir / "040_C40_part001.mp3"
    p2 = parts_dir / "040_C40_part002.mp3"
    p1.write_bytes(b"p1")
    p2.write_bytes(b"p2")
    chapter_mp3 = out / "040_C40.mp3"
    plan = ChapterPlan(40, "C40", str(chapter_mp3), [str(p1), str(p2)], [(40, "C40 - part 1", str(p1)), (40, "C40 - part 2", str(p2))])

    def failing_concat(paths, out_path):
        raise subprocess.CalledProcessError(returncode=1, cmd="ffmpeg")

    with patch("core.tts.ffmpeg_available", return_value=True):
        with patch("core.tts.concat_mp3_files", side_effect=failing_concat):
            entries = finalize_chapter_audio([plan], keep_parts=False)
    # fallback to marker entries
    assert entries == [(40, "C40 - part 1", str(p1)), (40, "C40 - part 2", str(p2))]
    assert "merge failed" in capsys.readouterr().out
    assert not chapter_mp3.exists()


def test_build_m4b_escape_integration(tmp_path, capsys):
    out = tmp_path / "out_escape"
    out.mkdir()
    a = out / "001.mp3"
    a.write_bytes(b"a")
    book_title = "T=;A#B\\C\nD"
    marker = "Ch;=1\n"
    audio_entries = [(1, marker, str(a))]
    captured = {}

    def fake_run(args, check=True, **kwargs):
        meta_path = out / "_metadata.txt"
        captured["meta"] = meta_path.read_text(encoding="utf-8")
        Path(args[-1]).write_bytes(b"x" * 1024)
        return MagicMock(returncode=0)

    with patch("core.tts.ffmpeg_available", return_value=True):
        with patch("core.tts.ffprobe_available", return_value=True):
            with patch("core.tts.probe_duration_ms", return_value=1000):
                with patch("core.tts.subprocess.run", side_effect=fake_run):
                    build_m4b(str(out), audio_entries, book_title, ext="m4b")
    # sanitized book_title
    sanitized = sanitize_filename(book_title, fallback="audiobook", max_len=120)
    assert f"title={escape_ffmeta(sanitized)}" in captured["meta"]
    assert "title=001 - Ch\\;\\=1\\n" in captured["meta"] or "Ch\\;\\=1" in captured["meta"]


def test_build_m4b_output_dir_and_ext_whitelist(tmp_path, capsys):
    out = tmp_path / "nonexist" / "sub"
    assert not out.exists()
    a = tmp_path / "a.mp3"
    a.write_bytes(b"a")
    entries = [(1, "Ch1", str(a))]

    def fake_run(args, check=True, **kwargs):
        # out_path should be m4b even when ext is traversal
        assert args[-1].endswith(".m4b.tmp")
        Path(args[-1]).parent.mkdir(parents=True, exist_ok=True)
        Path(args[-1]).write_bytes(b"x" * 1024)
        return MagicMock(returncode=0)

    with patch("core.tts.ffmpeg_available", return_value=True):
        with patch("core.tts.ffprobe_available", return_value=True):
            with patch("core.tts.probe_duration_ms", return_value=500):
                with patch("core.tts.subprocess.run", side_effect=fake_run):
                    build_m4b(str(out), entries, "book/title\\test", ext="../evil")
    # output_dir created
    assert out.exists()
    # book_title sanitized no slash
    assert not (out / "../evil").exists()
    assert any(p.suffix == ".m4b" for p in out.rglob("*.m4b"))


def test_build_m4b_cleanup_on_error(tmp_path, capsys):
    out = tmp_path / "out_cleanup"
    out.mkdir()
    a = out / "001.mp3"
    a.write_bytes(b"a")
    entries = [(1, "Ch1", str(a))]

    def failing_run(args, check=True, **kwargs):
        raise subprocess.CalledProcessError(returncode=1, cmd="ffmpeg")

    with patch("core.tts.ffmpeg_available", return_value=True):
        with patch("core.tts.ffprobe_available", return_value=True):
            with patch("core.tts.get_duration_ms", return_value=1000):
                with patch("core.tts.subprocess.run", side_effect=failing_run):
                    with pytest.raises(subprocess.CalledProcessError):
                        build_m4b(str(out), entries, "book", ext="m4b")
    # temps must be cleaned even on error
    assert not (out / "_concat.txt").exists()
    assert not (out / "_metadata.txt").exists()


def test_concat_cleanup_on_error(tmp_path):
    out = tmp_path / "out_concat_err.mp3"
    p1 = tmp_path / "p1.mp3"
    p1.write_bytes(b"x")

    def failing_run(args, check=True, stdout=None, stderr=None, **kwargs):
        raise subprocess.CalledProcessError(returncode=1, cmd="ffmpeg")

    with patch("core.tts.shutil.which", return_value="/usr/bin/ffmpeg"):
        with patch("core.tts.subprocess.run", side_effect=failing_run):
            with pytest.raises(subprocess.CalledProcessError):
                concat_mp3_files([str(p1)], str(out))
    concat_file = str(Path(str(out)).with_suffix(".concat.txt"))
    # ensure concat file cleaned
    assert not os.path.exists(concat_file)


def test_convert_wiring(tmp_path, monkeypatch):
    # Cover verification-gap V1: convert forwards keep_parts/book_title/ext correctly
    import speak as speak_mod
    import core.tts as core_mod

    fake_epub = tmp_path / "My Book.epub"
    fake_epub.write_bytes(b"fake")
    out_dir = tmp_path / "out_conv"
    chapters = [(36, "Ch36", "text" * 100), (37, "Ch37", "text" * 100)]

    called = {}

    def fake_extract(epub_path, start_chapter=1, end_chapter=None):
        called["extract"] = (epub_path, start_chapter, end_chapter)
        return chapters

    def fake_build_plan(chapters_arg, output_dir_arg, chunk_size_arg, rate=None, dialogue_voice=None, migrate_titles=False):
        called["build_plan"] = (output_dir_arg, chunk_size_arg, rate)
        # return plans with single-chunk chapters to simplify
        plans = [
            ChapterPlan(36, "Ch36", str(Path(output_dir_arg) / "036_Ch36.mp3"), [str(Path(output_dir_arg) / "036_Ch36.mp3")], [(36, "Ch36", str(Path(output_dir_arg) / "036_Ch36.mp3"))]),
            ChapterPlan(37, "Ch37", str(Path(output_dir_arg) / "037_Ch37.mp3"), [str(Path(output_dir_arg) / "037_Ch37.mp3")], [(37, "Ch37", str(Path(output_dir_arg) / "037_Ch37.mp3"))]),
        ]
        jobs = []
        return plans, jobs

    async def fake_run_jobs(jobs, voice, parallel, retries, rate=None, engine="edge", local_voice=None):
        called["run_jobs"] = (voice, parallel, retries, len(jobs), rate, engine, local_voice)

    def fake_finalize(plans, keep_parts, normalize_audio=False, trim_silence=False):
        called["finalize"] = (len(plans), keep_parts)
        return [(36, "Ch36", "/tmp/036_Ch36.mp3"), (37, "Ch37", "/tmp/037_Ch37.mp3")]

    def fake_build_m4b(output_dir_arg, entries, book_title_arg, ext_arg="m4b", bitrate="32k", cover_path=None, artist=None):
        called["build_m4b"] = (output_dir_arg, entries, book_title_arg, ext_arg, bitrate)

    monkeypatch.setattr(speak_mod, "extract_chapters", fake_extract)
    monkeypatch.setattr(speak_mod, "build_generation_plan", fake_build_plan)
    monkeypatch.setattr(speak_mod, "run_part_jobs", fake_run_jobs)
    monkeypatch.setattr(speak_mod, "finalize_chapter_audio", fake_finalize)
    monkeypatch.setattr(speak_mod, "build_m4b", fake_build_m4b)
    monkeypatch.setattr(speak_mod, "sanitize_filename", lambda v, fallback="audiobook", max_len=120: "My_Book")

    # m4b case
    asyncio.run(speak_mod.convert(str(fake_epub), str(out_dir), voice="en-US-AriaNeural", m4b=True, m4a=False, start_chapter=36, end_chapter=40, chunk_size=3500, keep_parts=True, parallel=3, retries=5))
    assert called["finalize"][1] is True
    assert called["build_m4b"][2] == "My_Book_chapters_036_to_040"
    assert called["build_m4b"][3] == "m4b"

    # m4a case
    called.clear()
    asyncio.run(speak_mod.convert(str(fake_epub), str(out_dir), voice="en-US-AriaNeural", m4b=False, m4a=True, start_chapter=36, end_chapter=None, chunk_size=3500, keep_parts=False, parallel=3, retries=5))
    assert called["build_m4b"][2] == "My_Book_from_chapter_036"
    assert called["build_m4b"][3] == "m4a"

    # neither m4b nor m4a -> no build_m4b
    called.clear()
    fake_build_m4b_called = False

    def fake_build_m4b_never(*a, **k):
        nonlocal fake_build_m4b_called
        fake_build_m4b_called = True

    monkeypatch.setattr(speak_mod, "build_m4b", fake_build_m4b_never)
    asyncio.run(speak_mod.convert(str(fake_epub), str(out_dir), voice="en-US-AriaNeural", m4b=False, m4a=False, start_chapter=36, end_chapter=None, chunk_size=3500, keep_parts=False, parallel=3, retries=5))
    assert fake_build_m4b_called is False

    # review cr2: rate/engine/local_voice must reach run_part_jobs — a bare
    # "25" (accepted by the CLI validator) canonicalizes to "+25%"
    called.clear()
    asyncio.run(speak_mod.convert(str(fake_epub), str(out_dir), voice="en-US-AriaNeural", m4b=False, m4a=False, start_chapter=36, end_chapter=None, chunk_size=3500, keep_parts=False, parallel=3, retries=5, rate="25", engine="local", local_voice="pl_PL-darkman-medium"))
    assert called["run_jobs"][4:] == ("+25%", "local", "pl_PL-darkman-medium")
    assert called["build_plan"][2] == "+25%"


def test_convert_ffmpeg_missing_warns_and_local_errors(tmp_path, monkeypatch, capsys):
    """Troubleshooter policy: ffmpeg is checked before any synthesis; the local
    engine fails fast, other engines proceed with a warning."""
    import speak as speak_mod

    fake_epub = tmp_path / "B.epub"
    fake_epub.write_bytes(b"fake")
    chapters = [(36, "Ch36", "text" * 100)]
    ran = {}

    async def fake_run_jobs(*a, **k):
        ran["jobs"] = True

    monkeypatch.setattr(speak_mod, "extract_chapters", lambda *a, **k: chapters)
    monkeypatch.setattr(speak_mod, "build_generation_plan", lambda *a, **k: ([], []))
    monkeypatch.setattr(speak_mod, "run_part_jobs", fake_run_jobs)
    monkeypatch.setattr(speak_mod, "finalize_chapter_audio", lambda plans, keep_parts=False, **kw: [])
    monkeypatch.setattr(speak_mod, "_core_ffmpeg", lambda: False)
    asyncio.run(speak_mod.convert(str(fake_epub), str(tmp_path / "o1"), voice="v", m4b=False, m4a=False))
    assert "ffmpeg not found" in capsys.readouterr().out
    assert ran.get("jobs") is True  # warning only: the build proceeds

    ran.clear()
    asyncio.run(speak_mod.convert(str(fake_epub), str(tmp_path / "o2"), voice="v", m4b=False, m4a=False,
                                  engine="local", local_voice="pl_PL-darkman-medium"))
    assert "requires ffmpeg" in capsys.readouterr().out
    assert "jobs" not in ran  # hard stop before any synthesis


# ---------------------------------------------------------------------------
# Story 4.1 — run_part_jobs callbacks: on_part_status sequence, skipped, error, progress/log
# ---------------------------------------------------------------------------

def test_run_part_jobs_callbacks_queued_fetching_done(tmp_path, capsys):
    out_dir = tmp_path / "out_cb"
    out_dir.mkdir()
    jobs = [
        PartJob(chapter_number=40, chapter_title="C40", part_number=1, part_count=2, text="hello world", output_path=str(out_dir / "_parts" / "040_C40_part001.mp3"), is_final_chapter_file=False),
        PartJob(chapter_number=40, chapter_title="C40", part_number=2, part_count=2, text="hello again", output_path=str(out_dir / "_parts" / "040_C40_part002.mp3"), is_final_chapter_file=False),
    ]
    (out_dir / "_parts").mkdir(parents=True, exist_ok=True)

    statuses = []
    logs = []
    progresses = []

    def on_part(payload):
        statuses.append(payload)

    def on_log(line):
        logs.append(line)

    def on_progress(done, total):
        progresses.append((done, total))

    async def fake_tts(text, output_path, voice, retries=5):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text("x", encoding="utf-8")

    async def _run():
        with patch("core.tts.tts_text_to_mp3", new=fake_tts):
            await run_part_jobs(jobs, voice="en-US-AndrewNeural", parallel=1, retries=5, on_part_status=on_part, on_log=on_log, on_progress=on_progress)

    asyncio.run(_run())

    # queued emitted for each job on enqueue (2)
    queued = [p for p in statuses if p["status"] == "queued"]
    assert len(queued) == 2
    assert queued[0]["chapter_number"] == 40 and queued[0]["part_number"] == 1 and queued[0]["part_count"] == 2 and queued[0]["is_final_chapter_file"] is False
    # fetching/done for each
    fetching = [p for p in statuses if p["status"] == "fetching"]
    done = [p for p in statuses if p["status"] == "done"]
    assert len(fetching) == 2
    assert len(done) == 2
    # order: queued,queued, fetching,done, fetching,done (reading order)
    assert statuses[0]["status"] == "queued" and statuses[1]["status"] == "queued"
    assert statuses[2]["status"] == "fetching" and statuses[2]["part_number"] == 1
    assert statuses[3]["status"] == "done" and statuses[3]["part_number"] == 1
    assert statuses[4]["status"] == "fetching" and statuses[4]["part_number"] == 2
    assert statuses[5]["status"] == "done" and statuses[5]["part_number"] == 2
    # logs contain start/done/progress
    assert any("start Chapter 040 part 001" in l for l in logs)
    assert any("done  Chapter 040 part 001" in l for l in logs)
    assert any("progress: 1/2" in l for l in logs)
    assert any("progress: 2/2" in l for l in logs)
    # progress callback
    assert progresses == [(1, 2), (2, 2)]
    # prints still happen for CLI compat
    out = capsys.readouterr().out
    assert "worker 1: start" in out
    assert "progress: 2/2" in out


def test_run_part_jobs_callbacks_skipped(tmp_path, capsys):
    out_dir = tmp_path / "out_skip_cb"
    out_dir.mkdir()
    parts_dir = out_dir / "_parts"
    parts_dir.mkdir(parents=True, exist_ok=True)
    p1 = parts_dir / "040_C40_part001.mp3"
    p1.write_text("x" * 2048, encoding="utf-8")
    p2 = parts_dir / "040_C40_part002.mp3"
    jobs = [
        PartJob(chapter_number=40, chapter_title="C40", part_number=1, part_count=2, text="c1", output_path=str(p1), is_final_chapter_file=False),
        PartJob(chapter_number=40, chapter_title="C40", part_number=2, part_count=2, text="c2", output_path=str(p2), is_final_chapter_file=False),
    ]
    statuses = []
    logs = []
    progresses = []

    def on_part(payload):
        statuses.append(payload)

    def on_log(line):
        logs.append(line)

    def on_progress(done, total):
        progresses.append((done, total))

    async def fake_tts(text, output_path, voice, retries=5):
        Path(output_path).write_text("generated", encoding="utf-8")

    async def _run():
        with patch("core.tts.tts_text_to_mp3", new=fake_tts):
            await run_part_jobs(jobs, voice="v", parallel=1, retries=5, on_part_status=on_part, on_log=on_log, on_progress=on_progress)

    asyncio.run(_run())

    assert len([s for s in statuses if s["status"] == "queued"]) == 2
    assert any(s["status"] == "skipped" and s["part_number"] == 1 for s in statuses)
    assert any(s["status"] == "fetching" and s["part_number"] == 2 for s in statuses)
    assert any(s["status"] == "done" and s["part_number"] == 2 for s in statuses)
    assert any("skip Chapter 040 part 001/002" in l for l in logs)
    assert any("progress: 1/2" in l for l in logs)
    assert any("progress: 2/2" in l for l in logs)
    assert progresses == [(1, 2), (2, 2)]
    assert not any("error" in s["status"] for s in statuses)
    # tts not called for skipped
    # verify file still exists
    assert p1.exists()


def test_run_part_jobs_callbacks_error(tmp_path, capsys):
    out_dir = tmp_path / "out_err_cb"
    out_dir.mkdir()
    parts_dir = out_dir / "_parts"
    parts_dir.mkdir(parents=True, exist_ok=True)
    jobs = [
        PartJob(chapter_number=40, chapter_title="C40", part_number=1, part_count=2, text="c1", output_path=str(parts_dir / "040_C40_part001.mp3"), is_final_chapter_file=False),
        PartJob(chapter_number=40, chapter_title="C40", part_number=2, part_count=2, text="c2", output_path=str(parts_dir / "040_C40_part002.mp3"), is_final_chapter_file=False),
    ]
    statuses = []
    logs = []

    def on_part(payload):
        statuses.append(payload)

    def on_log(line):
        logs.append(line)

    async def fake_tts(text, output_path, voice, retries=5):
        if "part001" in output_path:
            Path(output_path).write_text("ok", encoding="utf-8")
        else:
            raise RuntimeError("TTS failed after 5 attempts for test")

    async def _run():
        with patch("core.tts.tts_text_to_mp3", new=fake_tts):
            with pytest.raises(RuntimeError, match="TTS failed"):
                await run_part_jobs(jobs, voice="v", parallel=1, retries=5, on_part_status=on_part, on_log=on_log)

    asyncio.run(_run())

    # queued 2, fetching 1, done 1, fetching 2, error 1
    assert len([s for s in statuses if s["status"] == "queued"]) == 2
    assert any(s["status"] == "done" and s["part_number"] == 1 for s in statuses)
    assert any(s["status"] == "error" and s["part_number"] == 2 for s in statuses)
    assert any("error Chapter 040 part 002" in l for l in logs)


def test_run_part_jobs_callbacks_parallel_order_and_skipped6(tmp_path):
    out_dir = tmp_path / "out_para_cb"
    out_dir.mkdir()
    # 6 jobs across 2 chapters: ch40 3 parts, ch41 3 parts
    jobs = []
    for pn in range(1, 4):
        jobs.append(PartJob(chapter_number=40, chapter_title="C40", part_number=pn, part_count=3, text=f"c40-{pn}", output_path=str(out_dir / "_parts" / f"040_C40_part{pn:03d}.mp3"), is_final_chapter_file=False))
    for pn in range(1, 4):
        jobs.append(PartJob(chapter_number=41, chapter_title="C41", part_number=pn, part_count=3, text=f"c41-{pn}", output_path=str(out_dir / "_parts" / f"041_C41_part{pn:03d}.mp3"), is_final_chapter_file=False))
    (out_dir / "_parts").mkdir(parents=True, exist_ok=True)
    # pre-create one part to test skipped 1/6
    (out_dir / "_parts" / "040_C40_part001.mp3").write_text("x" * 2048, encoding="utf-8")

    statuses = []
    logs = []

    def on_part(payload):
        statuses.append(payload)

    def on_log(line):
        logs.append(line)

    progresses = []

    def on_progress(done, total):
        progresses.append((done, total))

    concurrent = {"cur": 0, "max": 0}
    lock = asyncio.Lock()

    async def fake_tts(text, output_path, voice, retries=5):
        async with lock:
            concurrent["cur"] += 1
            concurrent["max"] = max(concurrent["max"], concurrent["cur"])
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text("x", encoding="utf-8")
        await asyncio.sleep(0.01)
        async with lock:
            concurrent["cur"] -= 1

    async def _run():
        with patch("core.tts.tts_text_to_mp3", new=fake_tts):
            await run_part_jobs(jobs, voice="v", parallel=3, retries=5, on_part_status=on_part, on_log=on_log, on_progress=on_progress)

    asyncio.run(_run())

    # queued 6, skipped 1, fetching 5, done 5
    assert len([s for s in statuses if s["status"] == "queued"]) == 6
    assert len([s for s in statuses if s["status"] == "skipped"]) == 1
    assert len([s for s in statuses if s["status"] == "done"]) == 5
    assert "skip Chapter 040 part 001/003" in "".join(logs) or any("skip Chapter 040 part 001" in l for l in logs)
    assert progresses[-1] == (6, 6)
    assert concurrent["max"] <= 3
    # reading order queued before fetching: first 6 statuses are queued
    assert all(s["status"] == "queued" for s in statuses[:6])


# ---------------------------------------------------------------------------
# Part-audio verification — anti-gap gate (truncated Edge TTS output)
# ---------------------------------------------------------------------------


def test_verify_part_audio_missing(tmp_path):
    ok, reason = verify_part_audio(str(tmp_path / "nope.mp3"), "some longer text here " * 10)
    assert (ok, reason) == (False, "missing")


def test_verify_part_audio_too_small(tmp_path):
    tiny = tmp_path / "tiny.mp3"
    tiny.write_bytes(b"x" * 100)
    assert verify_part_audio(str(tiny), "hello world this is longer than fifty chars " * 3) == (False, "too_small")


def test_verify_part_audio_size_ok_without_ffprobe(tmp_path):
    p = tmp_path / "ok.mp3"
    p.write_bytes(b"x" * 2048)
    with patch("core.tts.ffprobe_available", return_value=False):
        assert verify_part_audio(str(p), "a" * 1000) == (True, "ok_no_duration_check")


def test_verify_part_audio_short_text_skips_duration(tmp_path):
    p = tmp_path / "short.mp3"
    p.write_bytes(b"x" * 2048)
    with patch("core.tts.get_duration_ms") as mock_dur:
        ok, reason = verify_part_audio(str(p), "hi")
        assert (ok, reason) == (True, "ok_no_duration_check")
        mock_dur.assert_not_called()


def test_verify_part_audio_truncated_and_ok(tmp_path):
    p = tmp_path / "part.mp3"
    p.write_bytes(b"x" * 4096)
    text = "a" * 3500  # min expected = 3500*1000/15*0.5 ≈ 116667 ms
    with patch("core.tts.ffprobe_available", return_value=True):
        with patch("core.tts.get_duration_ms", return_value=30_000):
            assert verify_part_audio(str(p), text) == (False, "truncated")
        with patch("core.tts.get_duration_ms", return_value=250_000):
            assert verify_part_audio(str(p), text) == (True, "ok")


def test_verify_part_audio_rate_scales_duration_floor(tmp_path):
    # review cr2: a complete +100% part is ~half as long; an unscaled floor
    # would flag it "truncated" and abort the build with a chunk-size hint
    p = tmp_path / "fastrate.mp3"
    p.write_bytes(b"x" * 2048)
    text = "a" * 3000  # nominal floor = 3000/15*0.5 = 100 s; +100% floor = 50 s
    with patch("core.tts.ffprobe_available", return_value=True):
        with patch("core.tts.get_duration_ms", return_value=75_000):
            assert verify_part_audio(str(p), text) == (False, "truncated")
            assert verify_part_audio(str(p), text, rate="+100%") == (True, "ok")
            # slower rates never shorten audio: nominal floor still applies
            assert verify_part_audio(str(p), text, rate="-50%") == (False, "truncated")
            # garbage rate falls back to the nominal floor
            assert verify_part_audio(str(p), text, rate="fast") == (False, "truncated")


def test_verify_part_audio_no_duration(tmp_path):
    p = tmp_path / "nodur.mp3"
    p.write_bytes(b"x" * 2048)
    with patch("core.tts.ffprobe_available", return_value=True):
        with patch("core.tts.get_duration_ms", return_value=0):
            assert verify_part_audio(str(p), "a" * 1000) == (False, "no_duration")


def test_tts_empty_save_retries_then_succeeds(tmp_path, capsys):
    """Save writing an empty file counts as failed attempt: retry, then success."""
    out = tmp_path / "empty_retry.mp3"
    calls = {"n": 0}

    class FakeCommunicate:
        def __init__(self, text, voice_arg):
            pass

        async def save(self, path):
            calls["n"] += 1
            if calls["n"] == 1:
                Path(path).write_bytes(b"")
            else:
                Path(path).write_bytes(b"x" * 2048)

    async def fake_sleep(seconds):
        pass

    async def _run():
        with patch("edge_tts.Communicate", FakeCommunicate):
            with patch("core.tts.asyncio.sleep", new=fake_sleep):
                await tts_text_to_mp3("hello world", str(out), "v", retries=5)

    asyncio.run(_run())

    assert calls["n"] == 2
    assert out.stat().st_size == 2048
    assert "retry 1/4" in capsys.readouterr().out.lower()


def test_tts_truncated_auto_splits_and_heals(tmp_path, capsys):
    """Built-in troubleshooter: a truncated part is split and regenerated, not retried, not fatal."""
    out = tmp_path / "604_Chapter.mp3"
    long_text = "word " * 700  # 3500 chars -> duration check applies
    calls = {"save": 0}
    concats = []

    class FakeCommunicate:
        def __init__(self, text, voice_arg):
            pass

        async def save(self, path):
            calls["save"] += 1
            Path(path).write_bytes(b"x" * 4096)

    def fake_concat(inputs, output):
        concats.append(list(inputs))
        Path(output).write_bytes(b"x" * 4096)

    verify_calls = {"n": 0}

    def fake_verify(path, text=None, rate=None):
        verify_calls["n"] += 1
        if verify_calls["n"] == 1:
            return (False, "truncated")  # the full part: Edge cut it
        return (True, "ok")  # halves + reassembled output pass

    async def _run():
        with patch("edge_tts.Communicate", FakeCommunicate):
            with patch("core.tts.verify_part_audio", side_effect=fake_verify):
                with patch("core.tts.concat_mp3_files", side_effect=fake_concat):
                    with patch("core.tts.ffmpeg_available", return_value=True):
                        await tts_text_to_mp3(long_text, str(out), "v", retries=5)

    asyncio.run(_run())

    assert calls["save"] == 3  # full attempt + 2 halves, no pointless full retries
    assert len(concats) == 1 and len(concats[0]) == 2
    assert out.is_file()
    assert not list(tmp_path.glob("*.autosplit*.mp3"))  # temp halves cleaned
    assert "auto-splitting" in capsys.readouterr().out


def test_tts_truncated_normal_rate_retries_then_raises(tmp_path):
    """Below-floor truncation at a normal rate: suspect transient cut, so the
    troubleshooter retries the part instead of aborting — and surfaces the
    actionable error only after exhausting retries."""
    out = tmp_path / "trunc.mp3"
    calls = {"save": 0}
    short_text = "word " * 80  # 400 chars <= TRUNC_SPLIT_FLOOR: nothing to split

    class FakeCommunicate:
        def __init__(self, text, voice_arg):
            pass

        async def save(self, path):
            calls["save"] += 1
            Path(path).write_bytes(b"x" * 4096)

    async def fake_sleep(seconds):
        pass

    async def _run():
        with patch("edge_tts.Communicate", FakeCommunicate):
            with patch("core.tts.verify_part_audio", return_value=(False, "truncated")):
                with patch("core.tts.ffmpeg_available", return_value=True):
                    with patch("core.tts.asyncio.sleep", new=fake_sleep):
                        with pytest.raises(RuntimeError, match="even after automatic splitting"):
                            await tts_text_to_mp3(short_text, str(out), "v", retries=5)

    asyncio.run(_run())

    assert calls["save"] == 5  # initial + 4 plain re-saves, no pointless splitting
    assert not out.exists()  # invalid file removed, resume will regenerate


def test_tts_truncated_extreme_rate_raises_immediately(tmp_path):
    """At extreme rates the scaled floor is trustworthy: fail fast, no retries."""
    out = tmp_path / "trunc.mp3"
    calls = {"save": 0}
    short_text = "word " * 80  # 400 chars

    class FakeCommunicate:
        def __init__(self, text, voice_arg, **kwargs):
            pass

        async def save(self, path):
            calls["save"] += 1
            Path(path).write_bytes(b"x" * 4096)

    async def _run():
        with patch("edge_tts.Communicate", FakeCommunicate):
            with patch("core.tts.verify_part_audio", return_value=(False, "truncated")):
                with patch("core.tts.ffmpeg_available", return_value=True):
                    with pytest.raises(RuntimeError, match="even after automatic splitting"):
                        await tts_text_to_mp3(short_text, str(out), "v", retries=5, rate="+80%")

    asyncio.run(_run())

    assert calls["save"] == 1
    assert not out.exists()


def test_tts_truncated_normal_rate_heals_on_resave(tmp_path):
    """Demotion path: when auto-split cannot help but the cut was transient,
    a plain re-save heals the part without aborting."""
    out = tmp_path / "trunc.mp3"
    calls = {"save": 0}
    long_text = "word " * 700  # 3500 chars

    class FakeCommunicate:
        def __init__(self, text, voice_arg):
            pass

        async def save(self, path):
            calls["save"] += 1
            Path(path).write_bytes(b"x" * 4096)

    async def fake_sleep(seconds):
        pass

    async def no_split(*a, **k):
        return False

    async def _run():
        with patch("edge_tts.Communicate", FakeCommunicate):
            # auto-split disabled for isolation; first save truncated, resave ok
            with patch("core.tts._autosplit_truncated", new=no_split):
                with patch("core.tts.verify_part_audio", side_effect=[(False, "truncated"), (True, "ok")]):
                    with patch("core.tts.asyncio.sleep", new=fake_sleep):
                        await tts_text_to_mp3(long_text, str(out), "v", retries=5)

    asyncio.run(_run())

    assert calls["save"] == 2
    assert out.is_file()


def test_tts_truncated_exhaustion_prefers_actionable_error(tmp_path):
    """All retries truncated: surface the truncation error, not the generic wrapper."""
    out = tmp_path / "trunc.mp3"
    long_text = "word " * 700  # 3500 chars

    class FakeCommunicate:
        def __init__(self, text, voice_arg):
            pass

        async def save(self, path):
            Path(path).write_bytes(b"x" * 4096)

    async def fake_sleep(seconds):
        pass

    async def no_split(*a, **k):
        return False

    async def _run():
        with patch("edge_tts.Communicate", FakeCommunicate):
            with patch("core.tts._autosplit_truncated", new=no_split):
                with patch("core.tts.verify_part_audio", return_value=(False, "truncated")):
                    with patch("core.tts.asyncio.sleep", new=fake_sleep):
                        with pytest.raises(RuntimeError, match="even after automatic splitting"):
                            await tts_text_to_mp3(long_text, str(out), "v", retries=2)

    asyncio.run(_run())
    assert not out.exists()


def test_tts_truncated_without_ffmpeg_raises(tmp_path):
    """No ffmpeg => no concat => the troubleshooter cannot help, raise the original."""
    out = tmp_path / "trunc.mp3"
    long_text = "word " * 700  # 3500 chars

    class FakeCommunicate:
        def __init__(self, text, voice_arg):
            pass

        async def save(self, path):
            Path(path).write_bytes(b"x" * 4096)

    async def fake_sleep(seconds):
        pass

    async def _run():
        with patch("edge_tts.Communicate", FakeCommunicate):
            with patch("core.tts.verify_part_audio", return_value=(False, "truncated")):
                with patch("core.tts.ffmpeg_available", return_value=False):
                    with patch("core.tts.asyncio.sleep", new=fake_sleep):
                        with pytest.raises(RuntimeError, match="even after automatic splitting"):
                            await tts_text_to_mp3(long_text, str(out), "v", retries=5)

    asyncio.run(_run())
    assert not out.exists()


def test_tts_truncated_heal_failure_raises_and_cleans(tmp_path):
    """Persistently truncated everywhere: recursion bottoms out at the floor,
    nested recovery fails fast (no attempt multiplication), and exhaustion
    surfaces the actionable truncation error with temp cleanup."""
    out = tmp_path / "trunc.mp3"
    calls = {"save": 0}
    long_text = "word " * 700  # 3500 chars

    class FakeCommunicate:
        def __init__(self, text, voice_arg):
            pass

        async def save(self, path):
            calls["save"] += 1
            Path(path).write_bytes(b"x" * 4096)

    def broken_concat(inputs, output):
        raise RuntimeError("concat boom")

    async def fake_sleep(seconds):
        pass

    async def _run():
        with patch("edge_tts.Communicate", FakeCommunicate):
            with patch("core.tts.verify_part_audio", return_value=(False, "truncated")):
                with patch("core.tts.concat_mp3_files", side_effect=broken_concat):
                    with patch("core.tts.ffmpeg_available", return_value=True):
                        with patch("core.tts.asyncio.sleep", new=fake_sleep):
                            with pytest.raises(RuntimeError, match="even after automatic splitting"):
                                await tts_text_to_mp3(long_text, str(out), "v", retries=2)

    asyncio.run(_run())
    # full + first-half chain (halves fail fast, second halves never run once
    # the first raises) + 1 top-level resave; nested levels never demote
    # (that would multiply attempts exponentially)
    assert calls["save"] == 5
    assert not out.exists()
    assert not list(tmp_path.glob("*.autosplit*.mp3"))


def test_run_part_jobs_regenerates_invalid_part(tmp_path, capsys):
    """Resume must regenerate a stale tiny part instead of skipping the gap."""
    out_dir = tmp_path / "out_regen"
    parts_dir = out_dir / "_parts"
    parts_dir.mkdir(parents=True, exist_ok=True)
    stale = parts_dir / "040_C40_part001.mp3"
    stale.write_bytes(b"x" * 100)  # truncated leftover from an earlier run
    fresh = parts_dir / "040_C40_part002.mp3"
    jobs = [
        PartJob(chapter_number=40, chapter_title="C40", part_number=1, part_count=2, text="chunk one", output_path=str(stale), is_final_chapter_file=False),
        PartJob(chapter_number=40, chapter_title="C40", part_number=2, part_count=2, text="chunk two", output_path=str(fresh), is_final_chapter_file=False),
    ]
    calls = []

    async def fake_tts(text, output_path, voice, retries=5):
        calls.append(Path(output_path).name)
        Path(output_path).write_bytes(b"x" * 2048)

    async def _run():
        with patch("core.tts.tts_text_to_mp3", new=fake_tts):
            await run_part_jobs(jobs, voice="v", parallel=1, retries=5)

    asyncio.run(_run())

    assert sorted(calls) == ["040_C40_part001.mp3", "040_C40_part002.mp3"]
    assert stale.stat().st_size == 2048
    out = capsys.readouterr().out
    assert "regenerating" in out
    assert "skip" not in out.lower()


def test_build_generation_plan_requeues_tiny_part(tmp_path):
    """Plan guard must re-queue a tiny stale part file (resume heals gaps)."""
    out = str(tmp_path / "out_requeue")
    os.makedirs(out, exist_ok=True)
    chapters = [(40, "C40", "a" * 4000)]  # 2 chunks
    plans, jobs = build_generation_plan(chapters, out, 3500)
    assert len(jobs) == 2
    # simulate stale truncated download of part 1
    Path(plans[0].part_paths[0]).write_bytes(b"x")
    _, jobs2 = build_generation_plan(chapters, out, 3500)
    assert Path(jobs2[0].output_path).name == "040_C40_part001.mp3"


def test_build_generation_plan_drops_gapped_merged_file(tmp_path, capsys):
    """A merged chapter MP3 built from truncated parts must not shadow them."""
    out = str(tmp_path / "out_gapped")
    os.makedirs(out, exist_ok=True)
    chapters = [(40, "C40", "a" * 4000)]  # 2 chunks, full text 4000 chars
    plans, _ = build_generation_plan(chapters, out, 3500)
    merged = Path(plans[0].chapter_mp3)
    merged.write_bytes(b"x" * 4096)  # stale merge containing only a fragment
    with patch("core.tts.ffprobe_available", return_value=True):
        with patch("core.tts.get_duration_ms", return_value=5_000):  # ~10% of expected
            _, jobs = build_generation_plan(chapters, out, 3500)
    assert not merged.exists()  # gapped merge dropped
    assert sorted(Path(j.output_path).name for j in jobs) == [
        "040_C40_part001.mp3", "040_C40_part002.mp3",
    ]
    assert "re-generating" in capsys.readouterr().out


def test_build_generation_plan_keeps_valid_merged_file(tmp_path, capsys):
    """A merged chapter MP3 with plausible duration is still reused (no rework)."""
    out = str(tmp_path / "out_valid_merge")
    os.makedirs(out, exist_ok=True)
    chapters = [(40, "C40", "a" * 4000)]
    plans, _ = build_generation_plan(chapters, out, 3500)
    merged = Path(plans[0].chapter_mp3)
    merged.write_bytes(b"x" * 4096)
    with patch("core.tts.ffprobe_available", return_value=True):
        with patch("core.tts.get_duration_ms", return_value=280_000):  # ~4000/15 cps
            _, jobs = build_generation_plan(chapters, out, 3500)
    assert merged.exists()
    assert jobs == []
    assert "re-generating" not in capsys.readouterr().out


def test_build_generation_plan_drops_truncated_single_chapter(tmp_path):
    """Single-chunk chapter MP3 with implausible duration is re-queued."""
    out = str(tmp_path / "out_single_trunc")
    os.makedirs(out, exist_ok=True)
    chapters = [(5, "T", "Hello world " * 200)]  # 2400 chars, single chunk
    plans, _ = build_generation_plan(chapters, out, 3500)
    single = Path(plans[0].chapter_mp3)
    single.write_bytes(b"x" * 2048)
    with patch("core.tts.ffprobe_available", return_value=True):
        with patch("core.tts.get_duration_ms", return_value=2_000):
            _, jobs = build_generation_plan(chapters, out, 3500)
    assert not single.exists()
    assert len(jobs) == 1 and jobs[0].part_count == 1


# ---------------------------------------------------------------------------
# resolve_output_dir — CWD-robust output (WinError 5 when CWD is System32)
# ---------------------------------------------------------------------------


def _patch_denied_cwd(monkeypatch, tmp_path):
    """Fake an unwritable CWD (System32): probe says denied, mkdir is a tripwire.

    Returns (fake_cwd, touched): touched collects every mkdir attempted under
    the fake CWD — resolve_output_dir must never touch it, only probe it.
    """
    import os as _os

    fake_cwd = tmp_path / "System32"
    fake_cwd.mkdir()  # like the real System32: exists, but denied below
    real_mkdir = Path.mkdir
    real_writable = _os.access
    touched = []

    def _mkdir(self, *args, **kwargs):
        try:
            self.relative_to(fake_cwd)
        except ValueError:
            return real_mkdir(self, *args, **kwargs)
        touched.append(str(self))
        raise PermissionError(13, "Access is denied")

    def _writable(path):
        try:
            Path(path).relative_to(fake_cwd)
        except ValueError:
            return real_writable(path, _os.W_OK)
        return False

    monkeypatch.setattr(Path, "mkdir", _mkdir)
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: fake_cwd))
    monkeypatch.setattr("core.tts._is_writable", _writable)
    return fake_cwd, touched


def test_resolve_output_dir_absolute_passthrough(tmp_path):
    out = resolve_output_dir(tmp_path / "books")
    assert out.is_absolute()
    assert (tmp_path / "books").is_dir()


def test_resolve_output_dir_default_uses_writable_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = resolve_output_dir(None)
    assert out == (tmp_path / "output").resolve()
    assert out.is_dir()


def test_resolve_output_dir_falls_back_when_cwd_denied(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("core.tts.user_output_base", lambda: tmp_path / "docs")
    _, touched = _patch_denied_cwd(monkeypatch, tmp_path)
    out = resolve_output_dir(None)
    assert out == (tmp_path / "docs" / "output").resolve()
    assert out.is_dir()
    assert touched == [], "denied CWD must be probed, never touched"
    assert "not usable" in capsys.readouterr().out


def test_resolve_output_dir_explicit_relative_falls_back(tmp_path, monkeypatch):
    monkeypatch.setattr("core.tts.user_output_base", lambda: tmp_path / "docs")
    _, touched = _patch_denied_cwd(monkeypatch, tmp_path)
    out = resolve_output_dir("mybooks")
    assert out == (tmp_path / "docs" / "output").resolve()
    assert touched == [], "denied CWD must be probed, never touched"


def test_resolve_output_dir_explicit_absolute_denied_raises(tmp_path, monkeypatch):
    def _deny(self, *args, **kwargs):
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(Path, "mkdir", _deny)
    with pytest.raises(OSError):
        resolve_output_dir(tmp_path / "nope")


def test_resolve_output_dir_no_ensure_no_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path / "ghost"))
    out = resolve_output_dir(None, ensure=False)
    assert out == (tmp_path / "ghost" / "output").resolve()
    assert not (tmp_path / "ghost").exists()
    # unwritable probe -> fallback selected, still without creating anything
    monkeypatch.setattr("core.tts._is_writable", lambda path: False)
    out2 = resolve_output_dir(None, ensure=False)
    from core.tts import user_output_base

    assert out2 == (user_output_base() / "output").resolve()
    assert not (tmp_path / "ghost").exists()


# ---------------------------------------------------------------------------
# Speech rate: normalize + forwarding to edge_tts.Communicate
# ---------------------------------------------------------------------------


def test_normalize_tts_rate_matrix():
    assert normalize_tts_rate("+25%") == "+25%"
    assert normalize_tts_rate("15%") == "+15%"
    assert normalize_tts_rate("-30%") == "-30%"
    assert normalize_tts_rate("+ 15 %") == "+15%"
    assert normalize_tts_rate(15) == "+15%"
    assert normalize_tts_rate(-200) == "-100%"  # clamped
    assert normalize_tts_rate("+250%") == "+100%"  # clamped
    assert normalize_tts_rate("fast") == "+0%"  # garbage -> default
    assert normalize_tts_rate("fast", "+7%") == "+7%"  # custom default
    assert normalize_tts_rate(None) == "+0%"
    assert normalize_tts_rate(True) == "+0%"  # bool is not a number here


def test_tts_text_to_mp3_forwards_rate(tmp_path):
    out = tmp_path / "rate_fwd.mp3"
    seen = {}

    class FakeCommunicate:
        def __init__(self, text, voice_arg, **kwargs):
            seen["kwargs"] = kwargs

        async def save(self, path):
            Path(path).write_text("x" * 2048, encoding="utf-8")

    async def _run():
        with patch("edge_tts.Communicate", FakeCommunicate):
            await tts_text_to_mp3("hello", str(out), "en-US-AriaNeural", retries=2, rate="+25%")

    asyncio.run(_run())
    assert seen["kwargs"].get("rate") == "+25%"


def test_tts_text_to_mp3_omits_rate_when_none(tmp_path):
    out = tmp_path / "no_rate.mp3"
    seen = {}

    class FakeCommunicate:
        def __init__(self, text, voice_arg, **kwargs):
            seen["kwargs"] = kwargs

        async def save(self, path):
            Path(path).write_text("x" * 2048, encoding="utf-8")

    async def _run():
        with patch("edge_tts.Communicate", FakeCommunicate):
            await tts_text_to_mp3("hello", str(out), "en-US-AriaNeural", retries=2)

    asyncio.run(_run())
    assert "rate" not in seen["kwargs"]


def test_tts_text_to_mp3_abandons_hanging_save(tmp_path):
    """A stalled Edge websocket must not pin the worker forever.

    Regression: the whole global queue froze when save() never returned
    (production test, v0.3.7) — the attempt has to be abandoned and retried.
    """
    out = tmp_path / "hang.mp3"
    attempts = []
    retries_seen = []

    class HangingCommunicate:
        def __init__(self, text, voice_arg, **kwargs):
            attempts.append(1)

        async def save(self, path):
            await asyncio.sleep(30)  # never finishes in time

    async def fake_sleep(_seconds):
        return None

    def on_retry(attempt, err):
        retries_seen.append((attempt, type(err).__name__))

    async def _run():
        with patch("edge_tts.Communicate", HangingCommunicate):
            with patch("core.tts.EDGE_SAVE_TIMEOUT_MIN", 0.05):
                with patch("core.tts.EDGE_SAVE_TIMEOUT_MAX", 0.05):
                    with patch("core.tts.EDGE_SAVE_TIMEOUT_PER_CHAR", 0.0):
                        with patch("core.tts.asyncio.sleep", side_effect=fake_sleep):
                            with pytest.raises(RuntimeError):
                                await tts_text_to_mp3(
                                    "hello", str(out), "en-US-AriaNeural", retries=2, on_retry=on_retry
                                )

    asyncio.run(_run())
    # the hanging save was abandoned and the attempt retried
    assert len(attempts) == 2
    assert retries_seen, "the abandoned attempt must be reported through on_retry"
    # no partial file was left behind
    assert not out.exists()


def test_tts_text_to_mp3_on_retry_callback(tmp_path):
    out = tmp_path / "retry_cb.mp3"
    retries_seen = []

    class FakeCommunicate:
        calls = 0

        def __init__(self, text, voice_arg, **kwargs):
            pass

        async def save(self, path):
            FakeCommunicate.calls += 1
            if FakeCommunicate.calls == 1:
                raise RuntimeError("429")
            Path(path).write_text("x" * 2048, encoding="utf-8")

    async def fake_sleep(_seconds):
        pass

    def on_retry(attempt, err):
        retries_seen.append((attempt, str(err)))

    async def _run():
        with patch("edge_tts.Communicate", FakeCommunicate):
            with patch("core.tts.asyncio.sleep", new=fake_sleep):
                await tts_text_to_mp3("hello", str(out), "en-US-AriaNeural", retries=5, on_retry=on_retry)

    asyncio.run(_run())
    assert retries_seen == [(1, "429")]


def test_tts_text_to_mp3_on_retry_exception_does_not_mask_retry(tmp_path):
    out = tmp_path / "retry_cb2.mp3"

    class FakeCommunicate:
        calls = 0

        def __init__(self, text, voice_arg, **kwargs):
            pass

        async def save(self, path):
            FakeCommunicate.calls += 1
            if FakeCommunicate.calls == 1:
                raise RuntimeError("429")
            Path(path).write_text("x" * 2048, encoding="utf-8")

    async def fake_sleep(_seconds):
        pass

    def on_retry(_attempt, _err):
        raise ValueError("callback bug must not kill the retry loop")

    async def _run():
        with patch("edge_tts.Communicate", FakeCommunicate):
            with patch("core.tts.asyncio.sleep", new=fake_sleep):
                await tts_text_to_mp3("hello", str(out), "en-US-AriaNeural", retries=5, on_retry=on_retry)

    asyncio.run(_run())
    assert out.exists()


# ---------------------------------------------------------------------------
# AdaptiveGate (AIMD concurrency)
# ---------------------------------------------------------------------------


def test_adaptive_gate_grows_after_clean_streak():
    gate = AdaptiveGate(3, ADAPTIVE_MAX_PARALLEL)
    for _ in range(ADAPTIVE_GROW_AFTER - 1):
        gate.note_clean_success()
    assert gate.limit == 3
    gate.note_clean_success()
    assert gate.limit == 4


def test_adaptive_gate_halves_on_retry_with_floor_1():
    gate = AdaptiveGate(6, ADAPTIVE_MAX_PARALLEL)
    gate.note_retry()
    assert gate.limit == 3
    gate.note_retry()
    assert gate.limit == 1
    gate.note_retry()
    assert gate.limit == 1  # floor
    # retry resets the clean streak
    for _ in range(ADAPTIVE_GROW_AFTER - 1):
        gate.note_clean_success()
    assert gate.limit == 1
    gate.note_clean_success()
    assert gate.limit == 2


def test_adaptive_gate_ceiling_and_initial_clamp():
    gate = AdaptiveGate(99, 5)
    assert gate.limit == 5
    gate.note_clean_success()
    assert gate.limit == 5  # at ceiling, no growth, no crash
    gate2 = AdaptiveGate(0, ADAPTIVE_MAX_PARALLEL)
    assert gate2.limit == 1


def test_adaptive_gate_acquire_release_blocks_over_limit():
    async def _run():
        gate = AdaptiveGate(1, 2)
        await gate.acquire()
        assert gate.limit == 1

        async def second():
            await gate.acquire()
            return True

        task = asyncio.create_task(second())
        await asyncio.sleep(0.01)
        assert not task.done(), "second acquire must block while limit is 1"
        gate.release()
        assert await asyncio.wait_for(task, timeout=1) is True

    asyncio.run(_run())


def test_adaptive_gate_release_wakes_after_growth():
    async def _run():
        gate = AdaptiveGate(1, 2)
        await gate.acquire()

        async def second():
            return await gate.acquire()

        task = asyncio.create_task(second())
        await asyncio.sleep(0.01)
        assert not task.done()
        for _ in range(ADAPTIVE_GROW_AFTER):
            gate.note_clean_success()
        assert gate.limit == 2
        assert await asyncio.wait_for(task, timeout=1) is None
        gate.release()
        gate.release()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# run_part_jobs adaptive integration (rate forwarding + AIMD logs)
# ---------------------------------------------------------------------------


def _make_jobs(n, tmp_path):
    out_dir = tmp_path / "adaptive_out"
    out_dir.mkdir(exist_ok=True)
    jobs = []
    for i in range(n):
        jobs.append(
            PartJob(
                chapter_number=40,
                chapter_title="C40",
                part_number=i + 1,
                part_count=n,
                text="Sentence. " * 50,
                output_path=str(out_dir / f"040_C40_part{i + 1:03d}.mp3"),
                is_final_chapter_file=(i + 1 == n),
            )
        )
    return jobs


def test_run_part_jobs_adaptive_logs_reduce_and_increase(tmp_path):
    jobs = _make_jobs(16, tmp_path)
    calls = {"n": 0}
    logs = []

    async def fake_tts(text, output_path, voice, retries=5, rate=None, on_retry=None):
        first = calls["n"] == 0
        calls["n"] += 1
        if first and on_retry is not None:
            on_retry(1, RuntimeError("429"))
        Path(output_path).write_text("x" * 1024, encoding="utf-8")
        await asyncio.sleep(0)

    async def _run():
        with patch("core.tts.tts_text_to_mp3", new=fake_tts):
            await run_part_jobs(
                jobs, voice="en-US-AndrewNeural", parallel=3, retries=5,
                adaptive=True, on_log=logs.append,
            )

    asyncio.run(_run())
    joined = "\n".join(logs)
    assert "parallel: throttling detected, reducing TTS concurrency 3 -> 1" in joined
    assert "parallel: stable, increasing TTS concurrency 1 -> 2" in joined
    # one retry consumed the streak: 15 clean parts -> exactly one +1 growth
    assert "increasing TTS concurrency 2 -> 3" not in joined


def test_run_part_jobs_adaptive_forward_rate_and_parallel_max(tmp_path):
    jobs = _make_jobs(4, tmp_path)
    seen_rates = []

    async def fake_tts(text, output_path, voice, retries=5, rate=None, on_retry=None):
        seen_rates.append(rate)
        Path(output_path).write_text("x" * 1024, encoding="utf-8")
        await asyncio.sleep(0)

    async def _run():
        with patch("core.tts.tts_text_to_mp3", new=fake_tts):
            await run_part_jobs(
                jobs, voice="en-US-AndrewNeural", parallel=2, retries=5,
                rate="+40%", adaptive=True, parallel_max=3,
            )

    asyncio.run(_run())
    assert seen_rates == ["+40%"] * 4


def test_run_part_jobs_legacy_callers_keep_strict_kwargs(tmp_path):
    """Legacy callers/fakes: no rate/on_retry kwargs when the gate is off."""
    jobs = _make_jobs(2, tmp_path)
    seen_retries = []

    async def fake_tts(text, output_path, voice, retries=5):
        seen_retries.append(retries)
        Path(output_path).write_text("x" * 1024, encoding="utf-8")
        await asyncio.sleep(0)

    async def _run():
        with patch("core.tts.tts_text_to_mp3", new=fake_tts):
            await run_part_jobs(jobs, voice="en-US-AndrewNeural", parallel=2, retries=5)

    asyncio.run(_run())
    assert seen_retries == [5, 5]


# ---------------------------------------------------------------------------
# Feature pack: dialogue voices, title pause, build identity, post-processing,
# M4B metadata (artist/cover) — core-level tests
# ---------------------------------------------------------------------------

def test_split_dialogue_segments_polish_and_straight_quotes():
    text = 'Narration. „Yes, hello,” he said. Then more. "Second voice here." End.'
    segs = split_dialogue(text)
    flags = [d for _, d in segs]
    # whole input covered: rejoin matches original modulo whitespace-only pieces
    assert "".join(s for s, _ in segs) == text
    assert any("„Yes, hello,”" in s and d for s, d in segs)
    assert any('"Second voice here."' in s and d for s, d in segs)
    assert any("Narration." in s and not d for s, d in segs)
    assert any("Then more." in s and not d for s, d in segs)


def test_split_dialogue_unmatched_quotes_stay_narration():
    text = 'He said: „never closed. Keep going.'
    segs = split_dialogue(text)
    assert len(segs) == 1
    assert segs[0][0] == text and segs[0][1] is False


def test_split_dialogue_no_dialogue_returns_input_untouched():
    text = "Plain narration without any quotes at all."
    segs = split_dialogue(text)
    assert segs == [(text, False)]
    assert split_dialogue("") == []
    assert split_dialogue(None) == []


def test_split_title_body_splits_matching_prefix():
    title = "Rozdział 12"
    body = "Rozdział 12\n\nNad morzem wiało."
    t, rest = split_title_body(title, body)
    assert t == "Rozdział 12"
    assert rest.startswith("Nad morzem")


def test_split_title_body_no_match_keeps_text_intact():
    title = "The Long Title"
    body = "Different opening sentence entirely."
    t, rest = split_title_body(title, body)
    assert t is None
    assert rest == body  # untouched canonical body


def test_split_title_body_strip_only_leading_title():
    title = "Rozdzial"
    body = "Intro. Midnight struck."
    t, rest = split_title_body(title, "Rozdzial. Intro. Midnight struck.")
    assert t == "Rozdzial"
    assert rest == "Intro. Midnight struck."
    # trailing match not honored: title must be a *prefix*
    t2, rest2 = split_title_body(title, "Midnight struck at Rozdzial")
    assert t2 is None and rest2 == "Midnight struck at Rozdzial"


def test_ensure_pause_file_generated_once(tmp_path):
    calls = []

    def fake_run(args, check=True, **kwargs):
        calls.append(args)
        Path(args[-1]).write_bytes(b"silence")

    with patch("core.tts.ffmpeg_available", return_value=True):
        with patch("core.tts.shutil.which", return_value="ffmpeg"):
            with patch("core.tts.subprocess.run", side_effect=fake_run):
                p1 = ensure_pause_file(str(tmp_path), 1.0)
                p2 = ensure_pause_file(str(tmp_path), 1.0)

    assert p1 == p2 == str(tmp_path / "_pause_1s.mp3")
    assert Path(p1).is_file()
    assert len(calls) == 1  # cached on the second call
    cmd = " ".join(calls[0])
    assert "anullsrc" in cmd and "24000" in cmd
    # different duration gets its own file
    with patch("core.tts.ffmpeg_available", return_value=True):
        with patch("core.tts.shutil.which", return_value="ffmpeg"):
            with patch("core.tts.subprocess.run", side_effect=lambda a, **k: Path(a[-1]).write_bytes(b"s")):
                ensure_pause_file(str(tmp_path), 2.0)
    assert (tmp_path / "_pause_2s.mp3").is_file()


def test_ensure_pause_file_no_ffmpeg_returns_none(tmp_path):
    with patch("core.tts.ffmpeg_available", return_value=False):
        assert ensure_pause_file(str(tmp_path)) is None


def test_append_silence_concat_replaces_atomically(tmp_path):
    part = tmp_path / "title.mp3"
    pause = tmp_path / "_pause_1s.mp3"
    part.write_text("title", encoding="utf-8")
    pause.write_text("…", encoding="utf-8")

    def fake_concat(inputs, outp):
        Path(outp).write_text("|".join(inputs), encoding="utf-8")

    with patch("core.tts.concat_mp3_files", side_effect=fake_concat):
        from core.tts import _append_silence

        _append_silence(str(part), str(pause))

    # final file has the silence appended, tmp gone
    assert part.read_text(encoding="utf-8") == f"{part}|{pause}"
    assert not (tmp_path / "title.mp3.pausetmp").exists()


def test_check_build_identity_missing_manifest_is_fresh(tmp_path):
    wiped, fresh = check_build_identity(str(tmp_path), {"rate": "+0%", "voice": "V"})
    assert (wiped, fresh) == (False, True)
    with open(tmp_path / ".speak-epub-build.json", encoding="utf-8") as f:
        stored = json.load(f)
    assert stored["rate"] == "+0%" and stored["plan"] == 4
    # the identity covers everything that changes the spoken audio
    for key in ("rate", "voice", "engine", "chunk_size", "filters", "auto_boilerplate", "source"):
        assert key in stored


def test_check_build_identity_matching_is_pure_resume(tmp_path):
    check_build_identity(str(tmp_path), {"rate": "+0%", "voice": "V"})
    wiped, fresh = check_build_identity(str(tmp_path), {"rate": "+0%", "voice": "V"})
    assert (wiped, fresh) == (False, False)


def test_check_build_identity_change_wipes_generated_audio(tmp_path):
    identity = {"rate": "+0%", "voice": "V1"}
    check_build_identity(str(tmp_path), identity)
    parts = tmp_path / "_parts"
    parts.mkdir()
    (parts / "039_Ch_part001.mp3").write_bytes(b"x")
    (parts / "040_Ch.title.mp3").write_bytes(b"x")
    (tmp_path / "039_Ch.mp3").write_bytes(b"x")
    (tmp_path / "book.m4b").write_bytes(b"x")
    (tmp_path / "cover.jpg").write_bytes(b"x")  # never wiped (not generated)
    (tmp_path / "book.epub").write_bytes(b"x")  # never wiped

    wiped, fresh = check_build_identity(str(tmp_path), {"rate": "+25%", "voice": "V1"})
    assert wiped is True and fresh is False
    assert not (parts / "039_Ch_part001.mp3").exists()
    assert not (parts / "040_Ch.title.mp3").exists()
    assert not (tmp_path / "039_Ch.mp3").exists()
    assert not (tmp_path / "book.m4b").exists()
    assert (tmp_path / "cover.jpg").exists()
    assert (tmp_path / "book.epub").exists()
    with open(tmp_path / ".speak-epub-build.json", encoding="utf-8") as f:
        stored = json.load(f)
    assert stored["rate"] == "+25%"


def test_check_build_identity_corrupt_manifest_counts_as_fresh(tmp_path):
    (tmp_path / ".speak-epub-build.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "001_Ch.mp3").write_bytes(b"x")
    wiped, fresh = check_build_identity(str(tmp_path), {"rate": "+0%", "voice": "V"})
    # grandparented: existing files kept, no wipe
    assert (wiped, fresh) == (False, True)
    assert (tmp_path / "001_Ch.mp3").exists()


def test_check_build_identity_unwritable_manifest_never_wipes(tmp_path):
    check_build_identity(str(tmp_path), {"rate": "+0%", "voice": "V"})
    parts = tmp_path / "_parts"
    parts.mkdir()
    (parts / "040_Ch_part001.mp3").write_bytes(b"x")
    (tmp_path / "040_Ch.mp3").write_bytes(b"x")

    # recording the new identity fails -> nothing is deleted
    with patch("core.tts.json.dump", side_effect=OSError("denied")):
        wiped, fresh = check_build_identity(str(tmp_path), {"rate": "+50%", "voice": "V2"}, on_log=lambda m: None)

    assert (wiped, fresh) == (False, False)
    assert (parts / "040_Ch_part001.mp3").exists()
    assert (tmp_path / "040_Ch.mp3").exists()


def test_split_title_body_only_when_ffmpeg(tmp_path):
    """Without ffmpeg the legacy layout is kept byte-for-byte (no pause plan)."""
    chapters = [(7, "Rozdzial 7", "Rozdzial 7. Body text here. " * 30)]
    safe = sanitize_filename("Rozdzial 7", fallback="Chapter_007")
    with patch("core.tts.ffmpeg_available", return_value=False):
        plans, jobs = build_generation_plan(chapters, str(tmp_path / "out"), 3500)
    assert len(plans) == 1
    pdf = tmp_path / "out" / f"007_{safe}.mp3"
    assert plans[0].part_paths == [str(pdf)]
    assert plans[0].title_part_path is None


def test_build_generation_plan_dialogue_voice_override(tmp_path):
    chapters = [(5, "Ch5", 'Narration one, quite short. „Yes, hello,” she replied. Then narration two.')]
    with patch("core.tts.ffmpeg_available", return_value=True):
        with patch("core.tts._ensure_valid_or_drop", return_value=False):
            plans, jobs = build_generation_plan(
                chapters, str(tmp_path / "out"), 3500, dialogue_voice="pl_PL-darkman-medium"
            )
    assert len(plans) == 1
    voices = [(j.part_number, j.voice, j.append_silence_sec) for j in jobs]
    # three parts: narration, dialogue (override), narration
    assert [v for _, v, _ in voices] == [None, "pl_PL-darkman-medium", None]
    assert all(s == 0.0 for _, _, s in voices)
    assert [p for p, _, _ in voices] == [1, 2, 3]
    # dialogue text preserved in the dialogue part
    dlg_job = [j for j in jobs if j.voice][0]
    assert "Yes, hello," in dlg_job.text


def test_build_generation_plan_dialogue_voice_ignores_when_unset(tmp_path):
    chapters = [(5, "Ch5", 'Narration one. „Yes, hello,” she replied.')]
    plans, jobs = build_generation_plan(chapters, str(tmp_path / "out"), 3500)
    # legacy fast path: narration+dialogue in one chunk, no overrides
    assert plans[0].title_part_path is None
    assert len(jobs) == 1
    assert jobs[0].voice is None


def test_build_generation_plan_title_split_creates_title_part_with_pause(tmp_path, capsys):
    text = "Rozdzial 12. " + "Nad morzem wialo. " * 150
    chapters = [(12, "Rozdzial 12", text)]
    safe = sanitize_filename("Rozdzial 12", fallback="Chapter_012")
    with patch("core.tts.ffmpeg_available", return_value=True):
        with patch("core.tts._ensure_valid_or_drop", return_value=False):
            plans, jobs = build_generation_plan(chapters, str(tmp_path / "out"), 3500)
    assert len(plans) == 1
    plan = plans[0]
    out = tmp_path / "out"
    title_part = plan.title_part_path
    assert title_part == str(out / f"012_{safe}.title.mp3")
    assert plan.part_paths == [str(out / "_parts" / f"012_{safe}_part001.mp3")]
    # exactly one title job (part 0) with the built-in 1 s pause, no override
    title_jobs = [j for j in jobs if j.output_path == title_part]
    assert len(title_jobs) == 1
    assert title_jobs[0].part_number == 0
    assert title_jobs[0].append_silence_sec == TITLE_PAUSE_SEC == 1.0
    assert title_jobs[0].voice is None
    assert title_jobs[0].text.strip().startswith("Rozdzial 12")
    # body text no longer contains the title (never read twice)
    body_jobs = [j for j in jobs if j is not title_jobs[0]]
    assert all(not j.text.strip().startswith("Rozdzial 12") for j in body_jobs)


def test_build_generation_plan_title_no_prefix_match_keeps_legacy(tmp_path):
    body = "Something else entirely opens the chapter. " * 60
    chapters = [(13, "Very Different Heading", body)]
    with patch("core.tts.ffmpeg_available", return_value=True):
        with patch("core.tts._ensure_valid_or_drop", return_value=False):
            plans, jobs = build_generation_plan(chapters, str(tmp_path / "out"), 3500)
    assert plans[0].title_part_path is None
    assert all(j.get("part_number", 0) != 0 if isinstance(j, dict) else j.part_number != 0 for j in jobs)


def test_build_generation_plan_migrate_titles_drops_stale_first_part(tmp_path, capsys):
    text = "Rozdzial 14. " + "Nad morzem wialo. " * 200
    chapters = [(14, "Rozdzial 14", text)]
    out = tmp_path / "out"
    parts = out / "_parts"
    parts.mkdir(parents=True)
    safe = sanitize_filename("Rozdzial 14", fallback="Chapter_014")
    first_body = parts / f"014_{safe}_part001.mp3"
    first_body.write_bytes(b"legacy title baked in")

    with patch("core.tts.ffmpeg_available", return_value=True):
        with patch("core.tts._ensure_valid_or_drop", return_value=False):
            build_generation_plan(chapters, str(out), 3500, migrate_titles=True)

    assert not first_body.exists()  # deleted once: title audio baked in
    assert "title split off" in capsys.readouterr().out

    # a later run (no manifest/fresh semantics here) does NOT delete on its own
    first_body.write_bytes(b"fresh body part")
    with patch("core.tts.ffmpeg_available", return_value=True):
        with patch("core.tts._ensure_valid_or_drop", return_value=False):
            build_generation_plan(chapters, str(out), 3500, migrate_titles=False)
    assert first_body.exists()


def test_finalize_chapter_audio_merges_title_part_first(tmp_path):
    out = tmp_path
    title_part = out / "009_C9.title.mp3"
    body_part = out / "_parts" / "009_C9_part001.mp3"
    body_part.parent.mkdir(parents=True)
    title_part.write_bytes(b"title")
    body_part.write_bytes(b"body")
    plan = ChapterPlan(
        9,
        "C9",
        str(out / "009_C9.mp3"),
        [str(body_part)],
        [(9, "C9 - title", str(title_part)), (9, "C9 - part 1", str(body_part))],
        title_part_path=str(title_part),
    )

    with patch("core.tts.ffmpeg_available", return_value=True):
        with patch(
            "core.tts.concat_mp3_files",
            side_effect=lambda inputs, outp: Path(outp).write_text("|".join(inputs), encoding="utf-8"),
        ):
            entries = finalize_chapter_audio([plan], keep_parts=True)

    merged = (out / "009_C9.mp3").read_text(encoding="utf-8")
    # audio order: title (with pause already appended) -> body
    assert merged.split("|") == [str(title_part), str(body_part)]
    # title part survives keep_parts (only body parts are cleaned)
    entries_expect = [(9, "C9", str(out / "009_C9.mp3"))]
    assert entries == entries_expect


def test_finalize_chapter_audio_discovers_plan_with_title_fallback():
    # planning-level guard: ChapterPlan with title part still lists the
    # chapter file as the single entry, not separate title/part files
    plan = ChapterPlan(9, "C9", "/x/009_C9.mp3", ["/x/009_C9.mp3"], [], title_part_path=None)
    with patch("core.tts.ffmpeg_available", return_value=False):
        with patch("os.path.isfile", side_effect=lambda p: False):
            entries = finalize_chapter_audio([plan], keep_parts=True)
    assert entries == []  # missing -> warning only (no invention)


def test_run_part_jobs_voice_override_and_title_silence(tmp_path):
    out = tmp_path / "out"
    parts = out / "_parts"
    parts.mkdir(parents=True)
    title_path = out / "041_C41.title.mp3"
    dlg_path = parts / "041_C41_part001.mp3"
    jobs = [
        PartJob(
            chapter_number=41, chapter_title="C41", part_number=0, part_count=2,
            text="Tytul rozdzialu", output_path=str(title_path),
            is_final_chapter_file=False, append_silence_sec=1.0,
        ),
        PartJob(
            chapter_number=41, chapter_title="C41", part_number=1, part_count=2,
            text="„Hej, witaj,”", output_path=str(dlg_path),
            is_final_chapter_file=False, voice="pl_PL-darkman-medium",
        ),
    ]
    seen = []

    async def fake_tts(text, output_path, voice, retries=5):
        seen.append((output_path, voice))
        Path(output_path).write_bytes(b"audio")

    pause_calls = []
    with patch("core.tts.tts_text_to_mp3", new=fake_tts):
        with patch("core.tts.ensure_pause_file", side_effect=lambda d, s: str(tmp_path / "pause.mp3") if pause_calls.append((d, s)) is None else ""):
            with patch("core.tts._append_silence", side_effect=lambda a, b: pause_calls.append(("append", a, b))):
                asyncio.run(run_part_jobs(jobs, voice="en-US-AndrewNeural", parallel=1, retries=5))

    # dialogue job used its override, title job fell back to the run voice
    assert seen == [
        (str(title_path), "en-US-AndrewNeural"),
        (str(dlg_path), "pl_PL-darkman-medium"),
    ]
    # silence appended only to the title part
    appends = [c for c in pause_calls if c[0] == "append"]
    assert [a for _, a, _ in appends] == [str(title_path)]


def test_run_part_jobs_title_pause_skipped_without_ffmpeg(tmp_path, capsys):
    out = tmp_path / "out"
    out.mkdir()
    title_path = out / "042_C42.title.mp3"
    jobs = [
        PartJob(
            chapter_number=42, chapter_title="C42", part_number=0, part_count=1,
            text="T", output_path=str(title_path),
            is_final_chapter_file=False, append_silence_sec=1.0,
        )
    ]
    logs = []

    async def fake_tts(text, output_path, voice, retries=5):
        Path(output_path).write_bytes(b"audio")

    with patch("core.tts.tts_text_to_mp3", new=fake_tts):
        with patch("core.tts.ensure_pause_file", return_value=None):
            asyncio.run(run_part_jobs(jobs, voice="v", parallel=1, retries=5, on_log=logs.append))

    assert Path(title_path).read_bytes() == b"audio"  # part kept, pause dropped
    assert any("no pause appended" in l for l in logs)


def test_postprocess_chapter_file_flags(tmp_path):
    path = tmp_path / "009_C9.mp3"
    path.write_bytes(b"x")
    cmds = []

    def fake_run(args, check=True, **kwargs):
        cmds.append(" ".join(args))
        Path(args[-1]).write_bytes(b"processed")

    with patch("core.tts.ffmpeg_available", return_value=True):
        with patch("core.tts.shutil.which", return_value="ffmpeg"):
            with patch("core.tts.subprocess.run", side_effect=fake_run):
                assert postprocess_chapter_file(str(path), normalize_audio=True, trim_silence=False) is True
                assert postprocess_chapter_file(str(path), normalize_audio=False) is False  # nothing to do
                assert postprocess_chapter_file(str(path), normalize_audio=False, trim_silence=True) is True

    assert "loudnorm" in cmds[0] and "silenceremove" not in cmds[0]
    assert "silenceremove" in cmds[1] and "loudnorm" not in cmds[1]
    assert cmds[0].count("24000") >= 1 and "48k" in cmds[0]
    # trim must NOT use stop_periods (verified destructive: removes ALL
    # silence >= threshold anywhere in the stream in ffmpeg 8) — the repaired
    # chain trims via areverse + leading-only filter, keeping natural pacing
    assert "stop_periods" not in cmds[1]
    assert cmds[1].count("areverse") == 2 and "start_silence=2.0" in cmds[1]
    # the output file has no usable extension (".postmp") — ffmpeg cannot infer
    # a muxer from it, so the format must be given explicitly (regression:
    # "Unable to choose an output format" killed every post-processed chapter)
    assert "-f mp3" in cmds[0] and "-f mp3" in cmds[1]


def test_postprocess_chapter_file_failure_keeps_original(tmp_path, capsys):
    path = tmp_path / "010_C10.mp3"
    path.write_bytes(b"original")
    with patch("core.tts.ffmpeg_available", return_value=True):
        with patch("core.tts.shutil.which", return_value="ffmpeg"):
            with patch("core.tts.subprocess.run", side_effect=subprocess.CalledProcessError(1, "ffmpeg")):
                assert postprocess_chapter_file(str(path), normalize_audio=True) is False
    assert path.read_bytes() == b"original"
    assert "keeping original" in capsys.readouterr().out


def test_build_m4b_cover_and_artist_metadata(tmp_path, capsys):
    out = tmp_path / "out_m4b_cov"
    out.mkdir()
    a = out / "001_Ch1.mp3"
    b = out / "002_Ch2.mp3"
    a.write_bytes(b"a")
    b.write_bytes(b"b")
    cover = out / "cover.jpg"
    cover.write_bytes(b"coverbytes")
    audio_entries = [(1, "Ch1", str(a)), (2, "Ch2", str(b))]

    camera = []

    def fake_run(args, check=True, **kwargs):
        camera.append(args)
        meta = (out / "_metadata.txt").read_text(encoding="utf-8")
        assert "artist=Jane Writer" in meta
        Path(args[-1]).write_bytes(b"m4b" * 1024)
        return MagicMock(returncode=0)

    with patch("core.tts.ffmpeg_available", return_value=True):
        with patch("core.tts.ffprobe_available", return_value=True):
            with patch("core.tts.get_duration_ms", side_effect=[1000, 1000]):
                with patch("core.tts.subprocess.run", side_effect=fake_run):
                    build_m4b(
                        str(out), audio_entries, "book", ext="m4b",
                        cover_path=str(cover), artist="Jane Writer",
                    )

    args = camera[0]
    assert "-i" in args and str(cover) in args
    assert "-map" in args and "2:v" in args
    assert "-disposition:v" in args and "attached_pic" in args
    assert args.count("coverbytes_map") == 0
    assert (out / "book.m4b").exists()


def test_build_m4b_cover_retry_without_cover(tmp_path, capsys):
    out = tmp_path / "out_m4b_retry"
    out.mkdir()
    a = out / "001_Ch1.mp3"
    a.write_bytes(b"a")
    cover = out / "cover.png"
    cover.write_bytes(b"png")
    attempts = []

    def fake_run(args, check=True, **kwargs):
        attempts.append(list(args))
        if len(attempts) == 2:
            Path(args[-1]).write_bytes(b"ok")
            return MagicMock(returncode=0)
        raise RuntimeError("cover encode broke")

    with patch("core.tts.ffmpeg_available", return_value=True):
        with patch("core.tts.ffprobe_available", return_value=True):
            with patch("core.tts.get_duration_ms", side_effect=[1000]):
                with patch("core.tts.subprocess.run", side_effect=fake_run):
                    build_m4b(str(out), [(1, "Ch1", str(a))], "book", ext="m4b", cover_path=str(cover))

    assert len(attempts) == 2
    assert str(cover) in attempts[0]  # first try with cover
    assert str(cover) not in attempts[1]  # fallback without
    assert (out / "book.m4b").exists()


def test_build_m4b_no_artist_no_metadata_line(tmp_path):
    out = tmp_path / "out_m4b_noartist"
    out.mkdir()
    a = out / "001_Ch1.mp3"
    a.write_bytes(b"a")

    def fake_run(args, check=True, **kwargs):
        metadata_path = out / "_metadata.txt"
        meta = metadata_path.read_text(encoding="utf-8")
        assert "artist=" not in meta
        Path(args[-1]).write_bytes(b"m4b")
        return MagicMock(returncode=0)

    with patch("core.tts.ffmpeg_available", return_value=True):
        with patch("core.tts.ffprobe_available", return_value=True):
            with patch("core.tts.get_duration_ms", side_effect=[1000]):
                with patch("core.tts.subprocess.run", side_effect=fake_run):
                    build_m4b(str(out), [(1, "Ch1", str(a))], "book", ext="m4b")


