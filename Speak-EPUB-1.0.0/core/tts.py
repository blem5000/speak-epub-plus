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
import shutil
import subprocess
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


async def run_part_jobs(
    jobs: List[PartJob],
    voice: str,
    parallel: int,
    retries: int,
    on_part_status=None,
    on_log=None,
    on_progress=None,
) -> None:
    """
    Global parallel PartJob queue — deterministyczny reading-order.

    - asyncio.Queue[Optional[PartJob]] filled for job in jobs: put_nowait(job) then sentinel None×parallel
    - workers parallel = asyncio.create_task(worker(i+1)) for i in range(parallel)
    - worker while True: job=await queue.get(); if job is None: task_done/break
    - skip if os.path.exists(output_path): log skip + size_kb, no TTS call
    - else start/done logs + await tts_text_to_mp3
    - progress completed/total with completed_lock, queue.task_done, queue.join, gather, cancel on exception
    - empty jobs -> print No TTS jobs ... and return

    Callbacks mirroring fetch.py pattern:
    - on_part_status(payload: dict) with {chapter_number, part_number, part_count, is_final_chapter_file, status}
      status in queued/fetching/done/error/skipped
    - on_log(line: str)
    - on_progress(completed: int, total: int)
    """
    # clamp parallel 1-6 to avoid deadlock/ flood (edge)
    try:
        parallel = int(parallel)
        parallel = max(1, min(6, parallel))
    except Exception:
        parallel = 3
    try:
        retries = int(retries)
        if retries < 1:
            retries = 5
    except Exception:
        retries = 5

    if not jobs:
        print("No TTS jobs to generate. Existing files will be reused.")
        if on_log:
            try:
                on_log("No TTS jobs to generate. Existing files will be reused.")
            except Exception:
                pass
        return

    # emit queued for each job on enqueue (reading order)
    for job in jobs:
        if on_part_status:
            try:
                on_part_status(
                    {
                        "chapter_number": job.chapter_number,
                        "part_number": job.part_number,
                        "part_count": job.part_count,
                        "is_final_chapter_file": job.is_final_chapter_file,
                        "status": "queued",
                    }
                )
            except Exception:
                pass

    queue: asyncio.Queue[Optional[PartJob]] = asyncio.Queue()
    for job in jobs:
        queue.put_nowait(job)

    for _ in range(parallel):
        queue.put_nowait(None)

    total_jobs = len(jobs)
    completed = 0
    completed_lock = asyncio.Lock()

    def _emit_part(job: PartJob, status: str):
        if on_part_status:
            try:
                on_part_status(
                    {
                        "chapter_number": job.chapter_number,
                        "part_number": job.part_number,
                        "part_count": job.part_count,
                        "is_final_chapter_file": job.is_final_chapter_file,
                        "status": status,
                    }
                )
            except Exception:
                pass

    def _emit_log(msg: str):
        if on_log:
            try:
                on_log(msg)
            except Exception:
                pass

    async def worker(worker_id: int) -> None:
        nonlocal completed
        while True:
            job = await queue.get()
            if job is None:
                queue.task_done()
                break

            try:
                if os.path.exists(job.output_path):
                    try:
                        size_kb = os.path.getsize(job.output_path) // 1024
                    except OSError:
                        size_kb = 0
                    msg_skip = (
                        f"worker {worker_id}: skip Chapter {job.chapter_number:03d} "
                        f"part {job.part_number:03d}/{job.part_count:03d} ({size_kb} KB)"
                    )
                    print(msg_skip)
                    _emit_log(f"skip Chapter {job.chapter_number:03d} part {job.part_number:03d}/{job.part_count:03d}")
                    _emit_log(msg_skip)
                    _emit_part(job, "skipped")
                else:
                    msg_start = (
                        f"worker {worker_id}: start Chapter {job.chapter_number:03d} "
                        f"part {job.part_number:03d}/{job.part_count:03d}"
                    )
                    print(msg_start)
                    _emit_log(msg_start)
                    _emit_log(f"start Chapter {job.chapter_number:03d} part {job.part_number:03d}/{job.part_count:03d}")
                    _emit_part(job, "fetching")
                    try:
                        await tts_text_to_mp3(job.text, job.output_path, voice, retries=retries)
                    except Exception as e:
                        # error path: emit error and re-raise to propagate via gather
                        err_msg = f"error Chapter {job.chapter_number:03d} part {job.part_number:03d}/{job.part_count:03d}: {e}"
                        print(err_msg)
                        _emit_log(err_msg)
                        _emit_part(job, "error")
                        async with completed_lock:
                            completed += 1
                            prog = f"progress: {completed}/{total_jobs} TTS part job(s) complete"
                            print(prog)
                            _emit_log(prog)
                            if on_progress:
                                try:
                                    on_progress(completed, total_jobs)
                                except Exception:
                                    pass
                        raise
                    try:
                        size_kb = os.path.getsize(job.output_path) // 1024
                    except OSError:
                        size_kb = 0
                    msg_done = (
                        f"worker {worker_id}: done  Chapter {job.chapter_number:03d} "
                        f"part {job.part_number:03d}/{job.part_count:03d} ({size_kb} KB)"
                    )
                    print(msg_done)
                    _emit_log(msg_done)
                    _emit_log(f"done Chapter {job.chapter_number:03d} part {job.part_number:03d}/{job.part_count:03d}")
                    _emit_part(job, "done")

                async with completed_lock:
                    completed += 1
                    prog = f"progress: {completed}/{total_jobs} TTS part job(s) complete"
                    print(prog)
                    _emit_log(prog)
                    if on_progress:
                        try:
                            on_progress(completed, total_jobs)
                        except Exception:
                            pass
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


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None


def concat_mp3_files(input_paths: List[str], output_path: str) -> None:
    if not input_paths:
        raise ValueError("no input paths")
    if not ffmpeg_available():
        raise RuntimeError("ffmpeg is not available")

    # ensure parent exists (convert ensures output_dir but direct API may not)
    try:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    concat_file = str(Path(output_path).with_suffix(".concat.txt"))
    try:
        with open(concat_file, "w", encoding="utf-8") as f:
            for p in input_paths:
                safe = os.path.abspath(p).replace("\\", "/").replace("'", "\\'")
                f.write(f"file '{safe}'\n")

        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_file, "-c", "copy", output_path],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    finally:
        try:
            if os.path.exists(concat_file):
                os.remove(concat_file)
        except OSError:
            pass


def get_duration_ms(path: str) -> int:
    if not ffprobe_available():
        return 0

    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return 0
    # robust returncode check — mock without int returncode treated as 0 for backward compat
    rc = getattr(result, "returncode", 0)
    if isinstance(rc, int) and rc != 0:
        return 0
    try:
        raw = result.stdout.strip() if result.stdout else ""
        if not raw:
            return 0
        return int(float(raw) * 1000)
    except (ValueError, TypeError, OverflowError):
        return 0


def escape_ffmeta(s: str) -> str:
    if not isinstance(s, str):
        s = str(s) if s is not None else ""
    # spec: escape =;#\ and \n ; also handle \r for robustness
    return re.sub(r"([=;#\\])", r"\\\1", s).replace("\r", "\\r").replace("\n", "\\n")


def finalize_chapter_audio(plans: List[ChapterPlan], keep_parts: bool) -> List[AudioEntry]:
    audio_entries: List[AudioEntry] = []
    has_ffmpeg = ffmpeg_available()

    print("\nFinalizing chapter files...")

    for plan in plans:
        if not plan.part_paths:
            continue

        # Single-chunk chapter.
        if len(plan.part_paths) == 1 and plan.part_paths[0] == plan.chapter_mp3:
            # validate exists and non-empty / is file
            try:
                if os.path.isfile(plan.chapter_mp3) and os.path.getsize(plan.chapter_mp3) > 0:
                    audio_entries.append((plan.chapter_number, plan.title, plan.chapter_mp3))
                else:
                    # zero-byte or not a file -> treat as missing
                    if os.path.exists(plan.chapter_mp3):
                        print(f"Warning: chapter MP3 exists but empty/corrupt: {plan.chapter_mp3}")
                    print(f"Warning: missing chapter MP3: {plan.chapter_mp3}")
            except OSError:
                print(f"Warning: missing chapter MP3: {plan.chapter_mp3}")
            continue

        # Multi-part chapter.
        if os.path.isfile(plan.chapter_mp3):
            try:
                size = os.path.getsize(plan.chapter_mp3)
                if size == 0:
                    print(f"Warning: existing merged file empty, will re-merge: {plan.chapter_mp3}")
                else:
                    audio_entries.append((plan.chapter_number, plan.title, plan.chapter_mp3))
                    size_kb = size // 1024
                    print(f"Chapter {plan.chapter_number:03d}: existing merged file reused ({size_kb} KB)")
                    continue
            except OSError:
                pass

        missing_parts = [p for p in plan.part_paths if not os.path.exists(p)]
        if missing_parts:
            print(f"Warning: Chapter {plan.chapter_number:03d} has missing part files; keeping available parts only.")
            for entry in (plan.marker_entries_if_unmerged or []):
                try:
                    if os.path.exists(entry[2]):
                        audio_entries.append(entry)
                except Exception:
                    continue
            continue

        if has_ffmpeg:
            print(f"Chapter {plan.chapter_number:03d}: merging {len(plan.part_paths)} part(s)")
            try:
                concat_mp3_files(plan.part_paths, plan.chapter_mp3)
                audio_entries.append((plan.chapter_number, plan.title, plan.chapter_mp3))
            except Exception as e:
                print(f"Warning: Chapter {plan.chapter_number:03d} merge failed ({e}); keeping available parts only.")
                # cleanup partial output if created
                try:
                    if os.path.exists(plan.chapter_mp3):
                        os.remove(plan.chapter_mp3)
                except OSError:
                    pass
                for entry in (plan.marker_entries_if_unmerged or []):
                    try:
                        if os.path.exists(entry[2]):
                            audio_entries.append(entry)
                    except Exception:
                        continue

            if not keep_parts:
                for part_path in plan.part_paths:
                    try:
                        if os.path.exists(part_path):
                            os.remove(part_path)
                    except OSError:
                        continue
        else:
            print(f"Chapter {plan.chapter_number:03d}: ffmpeg unavailable, keeping {len(plan.part_paths)} part files")
            for entry in (plan.marker_entries_if_unmerged or []):
                try:
                    if os.path.exists(entry[2]):
                        audio_entries.append(entry)
                except Exception:
                    continue
            # fallback: if marker entries contain missing paths, already filtered; extend only existing
    # Try to remove empty _parts folder (exact name match).
    if not keep_parts:
        part_dirs = sorted({str(Path(p).parent) for plan in plans for p in plan.part_paths if Path(p).parent.name == "_parts"})
        for part_dir in part_dirs:
            try:
                os.rmdir(part_dir)
            except OSError:
                pass

    audio_entries.sort(key=lambda x: (x[0], x[2]))
    return audio_entries


def build_m4b(output_dir: str, audio_entries: List[AudioEntry], book_title: str, ext: str = "m4b") -> None:
    # defensive ext whitelist
    if ext not in ("m4b", "m4a"):
        ext = "m4b"
    # defensive book_title sanitization (prevent traversal / illegal chars)
    # caller already sanitizes via sanitize_filename, but re-sanitize defensively
    book_title = sanitize_filename(book_title, fallback="audiobook", max_len=120)
    if not ffmpeg_available():
        print(f"\nWarning: ffmpeg not found on PATH - skipping {ext.upper()} creation.")
        print("Install FFmpeg from https://ffmpeg.org/download.html and add it to PATH.")
        return
    if not ffprobe_available():
        print(f"\nWarning: ffprobe not found on PATH - skipping {ext.upper()} creation.")
        print("ffprobe is normally installed together with FFmpeg.")
        return

    # ensure output_dir exists for direct API callers
    try:
        os.makedirs(output_dir, exist_ok=True)
    except Exception:
        pass

    print(f"\nBuilding {ext.upper()}...")
    concat_file = os.path.join(output_dir, "_concat.txt")
    metadata_file = os.path.join(output_dir, "_metadata.txt")
    out_path = os.path.join(output_dir, f"{book_title}.{ext}")
    try:
        with open(concat_file, "w", encoding="utf-8") as f:
            for _, _, path in audio_entries:
                safe = os.path.abspath(path).replace("\\", "/").replace("'", "\\'")
                f.write(f"file '{safe}'\n")

        with open(metadata_file, "w", encoding="utf-8") as f:
            f.write(";FFMETADATA1\n")
            f.write(f"title={escape_ffmeta(book_title)}\n\n")
            cursor = 0
            for chapter_number, marker_title, path in audio_entries:
                try:
                    duration = get_duration_ms(path)
                except Exception:
                    duration = 0
                # defensive marker_title handling
                try:
                    marker_title_str = str(marker_title) if marker_title is not None else ""
                    chapter_number_int = int(chapter_number)
                except Exception:
                    marker_title_str = str(marker_title) if marker_title is not None else ""
                    chapter_number_int = 0
                chapter_title = f"{chapter_number_int:03d} - {marker_title_str}"
                f.write("[CHAPTER]\n")
                f.write("TIMEBASE=1/1000\n")
                f.write(f"START={cursor}\n")
                f.write(f"END={cursor + duration}\n")
                f.write(f"title={escape_ffmeta(chapter_title)}\n\n")
                cursor += duration

        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                concat_file,
                "-i",
                metadata_file,
                "-map_metadata",
                "1",
                "-c:a",
                "aac",
                "-b:a",
                "64k",
                out_path,
            ],
            check=True,
        )
    finally:
        try:
            if os.path.exists(concat_file):
                os.remove(concat_file)
        except OSError:
            pass
        try:
            if os.path.exists(metadata_file):
                os.remove(metadata_file)
        except OSError:
            pass

    try:
        size_mb = os.path.getsize(out_path) / (1024 * 1024)
    except OSError:
        print(f"Warning: expected output not found after ffmpeg: {out_path}")
        return
    print(f"{ext.upper()} saved: {out_path} ({size_mb:.1f} MB)")


__all__ = [
    "sanitize_filename",
    "PartJob",
    "ChapterPlan",
    "split_text_for_tts",
    "build_generation_plan",
    "tts_text_to_mp3",
    "run_part_jobs",
    "ffmpeg_available",
    "ffprobe_available",
    "concat_mp3_files",
    "get_duration_ms",
    "escape_ffmeta",
    "finalize_chapter_audio",
    "build_m4b",
]
