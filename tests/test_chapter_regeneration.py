"""Proof that regenerating one chapter re-queues only that chapter.

The GUI drops the artifacts of a single chapter and starts the build again.
The build must resume every other chapter from the files that are already
on disk — otherwise the feature would silently rebuild the whole book.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.tts import build_generation_plan, invalidate_chapter_artifacts  # noqa: E402


def _ffmpeg_available() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except Exception:
        return False


def _make_mp3(path: Path, seconds: float = 1.0) -> None:
    """A real (silent) MP3 — the resume guard verifies it with ffprobe."""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", f"anullsrc=r=24000:cl=mono",
            "-t", str(seconds), str(path),
        ],
        check=True,
        capture_output=True,
    )


@pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg is required for the resume guard")
def test_only_the_dropped_chapter_is_re_queued(tmp_path):
    out = tmp_path / "audio"
    out.mkdir(parents=True, exist_ok=True)
    chapters = [
        (1, "Pierwszy", "Tekst pierwszego rozdziału do wymowy."),
        (2, "Drugi", "Tekst drugiego rozdziału do wymowy."),
    ]

    # first build: every chapter is queued
    _, jobs = build_generation_plan(chapters, str(out), 3500)
    assert {j.chapter_number for j in jobs} == {1, 2}

    # simulate the produced files
    for job in jobs:
        _make_mp3(Path(job.output_path), 2.0)

    # second build with the files present: everything is resumed (no jobs)
    _, jobs_after = build_generation_plan(chapters, str(out), 3500)
    assert jobs_after == []

    # the user regenerates chapter 2 -> its artifacts are dropped
    removed = invalidate_chapter_artifacts(str(out), 2)
    assert removed, "the chapter artifacts must be removed"

    # third build: ONLY chapter 2 is queued again
    _, jobs_rebuilt = build_generation_plan(chapters, str(out), 3500)
    assert {j.chapter_number for j in jobs_rebuilt} == {2}
