"""
core/tts.py — TTS Chunking + PartJob queue (Story 3.1 ratyfikacja brownfield).

AD-1: GUI→Core→Port→Adapter — this module is pure Core-owned single source.
AD-8: EPUB as intermediate invariant; TTS reads only EPUB via extract_chapters.
AD-2: raw never filtered; no filtering here.

Ratifies Speak-EPUB-1.0.0/speak.py semantics:
- split_text_for_tts 3500 sentence-boundary r"(?<=[.!?;:])\\s+" + hard-cut fallback >3500
- PartJob frozen dataclass with chapter_title retained for speak.py compat
- build_generation_plan global queue reading-order ch40 p1..20 before ch41 p1
- sanitize_filename mirror speak.py:84 (no epub extra fallback)

Pure: only os/re/dataclasses/pathlib/typing — no adapters/*, no speak, no edge-tts/subprocess.
"""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

Chapter = Tuple[int, str, str]
AudioEntry = Tuple[int, str, str]


def sanitize_filename(value: str, fallback: str = "chapter", max_len: int = 60) -> str:
    """
    Mirror Speak-EPUB-1.0.0/speak.py:84 sanitize_filename.

    - replace [\\/:*?"<>|] with _
    - collapse whitespace
    - truncate max_len
    - fallback if empty
    """
    safe = re.sub(r'[\\/:*?"<>|]', "_", value).strip()
    safe = re.sub(r"\s+", " ", safe).strip()
    safe = safe[:max_len].strip()
    return safe or fallback


@dataclass(frozen=True)
class PartJob:
    chapter_number: int
    chapter_title: str
    part_number: int
    part_count: int
    text: str
    output_path: str
    is_final_chapter_file: bool


@dataclass
class ChapterPlan:
    chapter_number: int
    title: str
    chapter_mp3: str
    part_paths: List[str]
    marker_entries_if_unmerged: List[AudioEntry]


def split_text_for_tts(text: str, max_chars: int = 3500) -> List[str]:
    """
    Sentence-boundary chunking with hard-cut fallback.

    - whitespace collapse re.sub r"\\s+" then strip
    - split at (?<=[.!?;:])\\s+
    - current flush, len(sentence)>max_chars -> hard cut while start
    - all chunks <=max_chars, order preserved via chunks.append
    """
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    sentences = re.split(r"(?<=[.!?;:])\s+", text)
    chunks: List[str] = []
    current = ""

    def flush_current() -> None:
        nonlocal current
        if current.strip():
            chunks.append(current.strip())
            current = ""

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        if len(sentence) > max_chars:
            flush_current()
            start = 0
            while start < len(sentence):
                part = sentence[start : start + max_chars].strip()
                if part:
                    chunks.append(part)
                start += max_chars
            continue

        if not current:
            current = sentence
        elif len(current) + 1 + len(sentence) <= max_chars:
            current += " " + sentence
        else:
            flush_current()
            current = sentence

    flush_current()
    return chunks


def build_generation_plan(
    chapters: List[Chapter], output_dir: str, chunk_size: int
) -> Tuple[List[ChapterPlan], List[PartJob]]:
    """
    Build global PartJob queue in reading order.

    - for chapter in chapters: for part in chunks: queue.append(PartJob)
    - ch40 p1..20 entirely before ch41 p1
    - sanitize title via sanitize_filename
    - output paths: f"{chapter_number:03d}_{safe}_part{part_number:03d}.mp3" in _parts for multi
      single-chunk "{chapter_number:03d}_{safe}.mp3" with is_final_chapter_file=True
    - guard: if not exists(chapter_mp3) and not exists(part_path): jobs.append (resume hint for 3.2)
      single guard: if not exists(chapter_mp3): jobs.append
    - ChapterPlan mirror speak.py:75
    - empty chunks -> plan with [],[] and no jobs
    Pure, no edge_tts/subprocess.
    """
    plans: List[ChapterPlan] = []
    jobs: List[PartJob] = []
    part_dir = os.path.join(output_dir, "_parts")

    for chapter_number, title, text in chapters:
        safe_title = sanitize_filename(title, fallback=f"Chapter_{chapter_number:03d}")
        chapter_mp3 = os.path.join(output_dir, f"{chapter_number:03d}_{safe_title}.mp3")
        chunks = split_text_for_tts(text, max_chars=chunk_size)

        if not chunks:
            plans.append(ChapterPlan(chapter_number, title, chapter_mp3, [], []))
            continue

        if len(chunks) == 1:
            plans.append(
                ChapterPlan(chapter_number, title, chapter_mp3, [chapter_mp3], [(chapter_number, title, chapter_mp3)])
            )
            if not os.path.exists(chapter_mp3):
                jobs.append(
                    PartJob(
                        chapter_number=chapter_number,
                        chapter_title=title,
                        part_number=1,
                        part_count=1,
                        text=chunks[0],
                        output_path=chapter_mp3,
                        is_final_chapter_file=True,
                    )
                )
            continue

        os.makedirs(part_dir, exist_ok=True)
        part_paths: List[str] = []
        marker_entries: List[AudioEntry] = []

        for part_number, chunk in enumerate(chunks, 1):
            part_path = os.path.join(part_dir, f"{chapter_number:03d}_{safe_title}_part{part_number:03d}.mp3")
            part_paths.append(part_path)
            marker_entries.append((chapter_number, f"{title} - part {part_number}", part_path))

            if not os.path.exists(chapter_mp3) and not os.path.exists(part_path):
                jobs.append(
                    PartJob(
                        chapter_number=chapter_number,
                        chapter_title=title,
                        part_number=part_number,
                        part_count=len(chunks),
                        text=chunk,
                        output_path=part_path,
                        is_final_chapter_file=False,
                    )
                )

        plans.append(ChapterPlan(chapter_number, title, chapter_mp3, part_paths, marker_entries))

    return plans, jobs


async def tts_text_to_mp3(text: str, output_path: str, voice: str, retries: int = 5) -> None:
    """
    Core-owned Edge TTS execution (ratyfikacja speak.py:116).

    - edge_tts lazy import inside loop (CI without deps still imports core.tts)
    - for attempt in 1..retries: edge_tts.Communicate(text,voice).save
    - wait = min(20, 2*attempt) + asyncio.sleep + log retry {attempt}/{retries-1} for {name}
    - raise RuntimeError after exhausting retries with last_error chained

    Pure Core — no adapters/*, no FFmpeg/epub/filters.
    """
    last_error: Optional[Exception] = None

    for attempt in range(1, retries + 1):
        try:
            import edge_tts  # lazy — keep core importable without edge-tts

            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(output_path)
            return
        except (ModuleNotFoundError, ImportError) as e:
            raise RuntimeError(f"edge-tts not installed for {output_path}: {e}") from e
        except Exception as e:
            last_error = e
            # clean partial file left by failed save to avoid resume skipping corrupt file
            try:
                p = Path(output_path)
                if p.is_file():
                    p.unlink(missing_ok=True)
            except Exception:
                pass
            if attempt < retries:
                wait_seconds = min(20, 2 * attempt)
                print(f"        retry {attempt}/{retries - 1} for {Path(output_path).name}: {e}")
                await asyncio.sleep(wait_seconds)

    raise RuntimeError(f"TTS failed after {retries} attempts for {output_path}: {last_error}") from last_error


async def run_part_jobs(jobs: List[PartJob], voice: str, parallel: int, retries: int) -> None:
    """
    Global parallel PartJob queue — deterministyczny reading-order.

    - asyncio.Queue[Optional[PartJob]] filled for job in jobs: put_nowait(job) then sentinel None×parallel
    - workers parallel = asyncio.create_task(worker(i+1)) for i in range(parallel)
    - worker while True: job=await queue.get(); if job is None: task_done/break
    - skip if os.path.exists(output_path): log skip + size_kb, no TTS call
    - else start/done logs + await tts_text_to_mp3
    - progress completed/total with completed_lock, queue.task_done, queue.join, gather, cancel on exception
    - empty jobs -> print No TTS jobs ... and return
    """
    if not jobs:
        print("No TTS jobs to generate. Existing files will be reused.")
        return

    queue: asyncio.Queue[Optional[PartJob]] = asyncio.Queue()
    for job in jobs:
        queue.put_nowait(job)

    for _ in range(parallel):
        queue.put_nowait(None)

    total_jobs = len(jobs)
    completed = 0
    completed_lock = asyncio.Lock()

    async def worker(worker_id: int) -> None:
        nonlocal completed
        while True:
            job = await queue.get()
            if job is None:
                queue.task_done()
                break

            try:
                if os.path.exists(job.output_path):
                    size_kb = os.path.getsize(job.output_path) // 1024
                    print(
                        f"worker {worker_id}: skip Chapter {job.chapter_number:03d} "
                        f"part {job.part_number:03d}/{job.part_count:03d} ({size_kb} KB)"
                    )
                else:
                    print(
                        f"worker {worker_id}: start Chapter {job.chapter_number:03d} "
                        f"part {job.part_number:03d}/{job.part_count:03d}"
                    )
                    await tts_text_to_mp3(job.text, job.output_path, voice, retries=retries)
                    size_kb = os.path.getsize(job.output_path) // 1024
                    print(
                        f"worker {worker_id}: done  Chapter {job.chapter_number:03d} "
                        f"part {job.part_number:03d}/{job.part_count:03d} ({size_kb} KB)"
                    )

                async with completed_lock:
                    completed += 1
                    print(f"progress: {completed}/{total_jobs} TTS part job(s) complete")
            finally:
                queue.task_done()

    workers = [asyncio.create_task(worker(i + 1)) for i in range(parallel)]

    try:
        await asyncio.gather(*workers)
        # ensure queue drained (workers already called task_done for each item)
        try:
            await asyncio.wait_for(queue.join(), timeout=0.1)
        except asyncio.TimeoutError:
            pass
    except Exception:
        for task in workers:
            task.cancel()
        # drain queue to unblock any waiting join
        while True:
            try:
                queue.get_nowait()
                queue.task_done()
            except asyncio.QueueEmpty:
                break
            except Exception:
                break
        raise


__all__ = [
    "sanitize_filename",
    "PartJob",
    "ChapterPlan",
    "split_text_for_tts",
    "build_generation_plan",
    "tts_text_to_mp3",
    "run_part_jobs",
]
