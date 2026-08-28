"""Tests for core/tts.py — I/O matrix Story 3.1 (ratyfikacja brownfield)."""
import os
import re
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from core.tts import split_text_for_tts, PartJob, build_generation_plan, sanitize_filename, ChapterPlan


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
