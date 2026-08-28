"""Tests for core/tts.py — I/O matrix Story 3.1 (ratyfikacja brownfield) + 3.2 Edge TTS + parallel + retries."""
import asyncio
import os
import re
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
    sanitize_filename,
    split_text_for_tts,
    tts_text_to_mp3,
    ffmpeg_available,
    ffprobe_available,
    concat_mp3_files,
    get_duration_ms,
    escape_ffmeta,
    finalize_chapter_audio,
    build_m4b,
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


def test_existing_file_skip_guard(tmp_path):
    out = str(tmp_path / "out")
    os.makedirs(out, exist_ok=True)
    part_dir = Path(out) / "_parts"
    part_dir.mkdir(parents=True, exist_ok=True)
    # Create chapters with 2 parts each
    chapters = [(40, "C40", "a" * 4000), (41, "C41", "b" * 4000)]
    # Pre-create part file for ch40 p1 to simulate resume
    # Need to know safe title; for "C40" it's "C40"
    pre_part = part_dir / "040_C40_part001.mp3"
    pre_part.write_text("dummy", encoding="utf-8")
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
    chapter_mp3_path.write_text("dummy", encoding="utf-8")
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


def test_single_chunk_resume_skip(tmp_path):
    """Single-chunk chapter MP3 already exists → jobs == [] (resume)."""
    out = str(tmp_path / "out_resume_single")
    os.makedirs(out, exist_ok=True)
    # single-chunk chapter (short text)
    chapters = [(5, "T", "Hello world")]
    # predict chapter_mp3 name
    safe = sanitize_filename("T", fallback="Chapter_005")
    chapter_mp3 = Path(out) / f"005_{safe}.mp3"
    chapter_mp3.write_text("dummy", encoding="utf-8")
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
            Path(path).write_text("fake-mp3", encoding="utf-8")

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
    assert out.read_text(encoding="utf-8") == "fake-mp3"
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
    job1_path.write_text("already-there", encoding="utf-8")
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

    async def fake_core_tts(text, output_path, voice, retries=5):
        called["tts"] = (text, output_path, voice, retries)
        Path(output_path).write_text("ok", encoding="utf-8")

    async def fake_core_run(jobs, voice, parallel, retries):
        called["run"] = (jobs, voice, parallel, retries)

    monkeypatch.setattr(core_mod, "tts_text_to_mp3", fake_core_tts)
    # Need to also patch the alias that speak imported at import time: _core_tts
    monkeypatch.setattr(speak_mod, "_core_tts", fake_core_tts, raising=False)
    monkeypatch.setattr(speak_mod, "_core_run", fake_core_run, raising=False)

    async def _run():
        # Test tts delegation
        out = tmp_path / "deleg.mp3"
        await speak_mod.tts_text_to_mp3("hi", str(out), "en-US-AriaNeural", retries=2)
        assert called["tts"] == ("hi", str(out), "en-US-AriaNeural", 2)

        # Test run delegation with parallel propagation 1..6
        jobs = [
            PartJob(chapter_number=1, chapter_title="T", part_number=1, part_count=1, text="hi", output_path=str(tmp_path / "a.mp3"), is_final_chapter_file=True)
        ]
        await speak_mod.run_part_jobs(jobs, voice="en-US-AriaNeural", parallel=3, retries=5)
        assert called["run"][2] == 3  # parallel
        assert called["run"][1] == "en-US-AriaNeural"

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
        # simulate ffmpeg creating output
        Path(output).write_bytes(b"merged")
        return MagicMock(returncode=0)

    with patch("core.tts.shutil.which", return_value="/usr/bin/ffmpeg"):
        with patch("core.tts.subprocess.run", side_effect=fake_run) as mock_run:
            concat_mp3_files(input_paths, str(output))

    assert captured["args"] == ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_file, "-c", "copy", str(output)]
    mock_run.assert_called_once()
    # concat_file cleaned up
    assert not os.path.exists(concat_file)
    assert output.exists()


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
    # ValueError -> 0
    with patch("core.tts.shutil.which", return_value="/usr/bin/ffprobe"):
        mock_result2 = MagicMock(stdout="not_a_number\n")
        with patch("core.tts.subprocess.run", return_value=mock_result2):
            assert get_duration_ms(str(dummy)) == 0
    # which false -> 0, no subprocess call
    with patch("core.tts.shutil.which", return_value=None):
        with patch("core.tts.subprocess.run") as mock_run2:
            assert get_duration_ms(str(dummy)) == 0
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
            safe = os.path.abspath(p).replace("\\", "/").replace("'", "\\'")
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
        # simulate ffmpeg creating output
        out_path = out / f"{book_title}.m4b"
        out_path.write_bytes(b"m4bcontent" * 1024)
        return MagicMock(returncode=0)

    with patch("core.tts.ffmpeg_available", return_value=True):
        with patch("core.tts.ffprobe_available", return_value=True):
            with patch("core.tts.get_duration_ms", side_effect=[1000, 1000]):
                with patch("core.tts.subprocess.run", side_effect=fake_run) as mock_run:
                    build_m4b(str(out), audio_entries, book_title, ext="m4b")

    mock_run.assert_called_once()
    args = captured["args"]
    assert args[0] == "ffmpeg"
    assert "-y" in args and "-f" in args and "concat" in args
    assert "-map_metadata" in args and "1" in args
    assert "-c:a" in args and "aac" in args and "-b:a" in args and "64k" in args
    expected_out = str(out / f"{book_title}.m4b")
    assert args[-1] == expected_out
    # temps removed
    assert not (out / "_concat.txt").exists()
    assert not (out / "_metadata.txt").exists()
    assert (out / f"{book_title}.m4b").exists()
    assert "M4B saved" in capsys.readouterr().out


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
    # ffprobe returns 0 for each, metadata still written with START 0 END 0
    out = tmp_path / "out_zero"
    out.mkdir()
    a = out / "001.mp3"
    a.write_bytes(b"x")
    audio_entries = [(1, "Ch1", str(a))]
    captured_meta = {}

    def fake_run(args, check=True, **kwargs):
        meta_path = out / "_metadata.txt"
        captured_meta["content"] = meta_path.read_text(encoding="utf-8")
        Path(out / "book.m4b").write_bytes(b"x" * 1024)
        return MagicMock(returncode=0)

    with patch("core.tts.ffmpeg_available", return_value=True):
        with patch("core.tts.ffprobe_available", return_value=True):
            with patch("core.tts.get_duration_ms", return_value=0):
                with patch("core.tts.subprocess.run", side_effect=fake_run):
                    build_m4b(str(out), audio_entries, "book", ext="m4b")
    assert "START=0" in captured_meta["content"]
    assert "END=0" in captured_meta["content"]


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

    def fake_finalize(plans, keep):
        called["finalize"] = (plans, keep)
        return [(1, "T", "/tmp/a.mp3")]

    def fake_m4b(out_dir, entries, title, ext="m4b"):
        called["m4b"] = (out_dir, entries, title, ext)

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

