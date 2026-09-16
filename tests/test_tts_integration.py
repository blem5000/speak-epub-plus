"""Integration parity: core.tts vs speak delegation (brownfield ratyfikacja)."""
import os
from pathlib import Path

import pytest

from core.tts import split_text_for_tts as core_split, build_generation_plan as core_build
import speak as speak_mod


def test_parity_split_random_texts():
    texts = [
        "Hello world",
        "   ",
        "Foo  \n  bar\t baz",
        "Sentence one. " * 800,  # ~11200
        "a" * 4000,
        "a" * 7001,
        "Foo! Bar? Baz; qux. " * 200,
        "a; b: c. d! e? f. " * 100,
        "Hello. " + "x" * 3600 + " world.",
        "First sentence. Second sentence! Third? Fourth; Fifth: Sixth. " * 100,
    ]
    for txt in texts:
        core_chunks = core_split(txt, 3500)
        speak_chunks = speak_mod.split_text_for_tts(txt, 3500)
        assert core_chunks == speak_chunks, f"mismatch for text len {len(txt)}"
        # Also ensure all <=3500
        assert all(len(c) <= 3500 for c in core_chunks)


def test_parity_build_generation_plan(tmp_path):
    out_core = str(tmp_path / "out_core")
    out_speak = str(tmp_path / "out_speak")
    os.makedirs(out_core, exist_ok=True)
    os.makedirs(out_speak, exist_ok=True)

    chapters_sets = [
        [(5, "T", "Hello world")],
        [(40, "C40", "a" * 4000), (41, "C41", "b" * 2000)],
        [(40, "C40", "x" * 7001), (41, "C41", "y" * 2000), (42, "C42", "z" * 7001)],
        [(1, "A/B:C?D*", "a" * 4000)],
        [(1, "Empty", "   "), (2, "Normal", "Hello")],
        [(10, "T10", "Sentence one. " * 800)],
    ]
    for chapters in chapters_sets:
        # Need separate out dirs to avoid _parts collisions? Use same tmp but different subdirs
        # Normalize output_path comparison to basename for cross-dir equality
        plans_core, jobs_core = core_build(chapters, out_core, 3500)
        plans_speak, jobs_speak = speak_mod.build_generation_plan(chapters, out_speak, 3500)

        # Compare job counts and fields
        assert len(jobs_core) == len(jobs_speak)
        for jc, js in zip(jobs_core, jobs_speak):
            assert jc.chapter_number == js.chapter_number
            assert jc.chapter_title == js.chapter_title
            assert jc.part_number == js.part_number
            assert jc.part_count == js.part_count
            assert jc.text == js.text
            assert jc.is_final_chapter_file == js.is_final_chapter_file
            # output_path basename should match (dirs differ)
            assert Path(jc.output_path).name == Path(js.output_path).name
            # _parts inclusion same — check parent folder name, not substring of tmp_path
            assert (Path(jc.output_path).parent.name == "_parts") == (Path(js.output_path).parent.name == "_parts")

        # Compare plans
        assert len(plans_core) == len(plans_speak)
        for pc, ps in zip(plans_core, plans_speak):
            assert pc.chapter_number == ps.chapter_number
            assert pc.title == ps.title
            assert Path(pc.chapter_mp3).name == Path(ps.chapter_mp3).name
            assert [Path(p).name for p in pc.part_paths] == [Path(p).name for p in ps.part_paths]
            # marker entries contain full paths — normalize to basename for parity (spec says after normalizacji output_path)
            norm_core = [(n, t, Path(p).name) for n, t, p in pc.marker_entries_if_unmerged]
            norm_speak = [(n, t, Path(p).name) for n, t, p in ps.marker_entries_if_unmerged]
            assert norm_core == norm_speak


def test_partjob_identity_same_class():
    # speak.PartJob should be same class as core.PartJob (import alias, not duplicate)
    assert speak_mod.PartJob is not None
    from core.tts import PartJob as CorePJ
    assert speak_mod.PartJob is CorePJ


def test_sanitize_parity():
    titles = ["A/B:C?D*", "Normal Title", "///", "  spaced   title  ", "a" * 100]
    for t in titles:
        from core.tts import sanitize_filename as core_san
        assert core_san(t) == speak_mod.sanitize_filename(t)


def test_parity_build_generation_plan_forwards_output_dir_and_chunk_size(tmp_path):
    """Ensure delegation forwards output_dir + chunk_size verbatim — basename-only would mask."""
    out_core = str(tmp_path / "out_core2")
    out_speak = str(tmp_path / "out_speak2")
    os.makedirs(out_core, exist_ok=True)
    os.makedirs(out_speak, exist_ok=True)
    chapters = [(5, "T", "a" * 4000)]
    # chunk_size 2000 should yield 2 parts, 3500 yields 2 as well but different splits, use 2000 vs 3500 diff
    plans_c2000, jobs_c2000 = core_build(chapters, out_core, 2000)
    plans_s2000, jobs_s2000 = speak_mod.build_generation_plan(chapters, out_speak, 2000)
    assert len(jobs_c2000) == 2
    assert len(jobs_s2000) == 2
    assert all(j.output_path.startswith(out_core) for j in jobs_c2000)
    assert all(j.output_path.startswith(out_speak) for j in jobs_s2000)
    # full path equality via basename already checked; now verify prefix matters: change out_core would still basename same but prefix must be correct
    assert Path(jobs_c2000[0].output_path).parent.name == "_parts"
    assert jobs_c2000[0].text == jobs_s2000[0].text
    # also verify speak forwarding isn't hard-coded 3500
    plans_c3500, jobs_c3500 = core_build(chapters, out_core, 3500)
    assert len(jobs_c2000) != len(jobs_c3500) or jobs_c2000[0].text != jobs_c3500[0].text
    # ensure speak with 2000 produces same as core with 2000 (and different from 3500)
    assert len(jobs_s2000) == len(jobs_c2000)
    assert jobs_s2000[0].text == jobs_c2000[0].text


def test_sanitize_parity_with_max_len_120():
    """Delegation must forward max_len — speake path uses max_len=120 for book title."""
    from core.tts import sanitize_filename as core_san

    title = "a" * 100
    assert core_san(title, max_len=120) == speak_mod.sanitize_filename(title, max_len=120)
    assert len(core_san(title, max_len=120)) == 100
    title2 = "b" * 150
    assert len(core_san(title2, max_len=120)) == 120
    assert core_san(title2, max_len=120) == speak_mod.sanitize_filename(title2, max_len=120)
    # max_len 60 vs 120 must differ for long titles
    assert core_san(title2, max_len=60) != core_san(title2, max_len=120)
    assert speak_mod.sanitize_filename(title2, max_len=60) == core_san(title2, max_len=60)
