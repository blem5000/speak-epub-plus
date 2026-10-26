#!/usr/bin/env python3
"""
speak.py - Speak EPUB
Convert an EPUB file to an audiobook using Microsoft Edge TTS.

This version adds:
  - --start-chapter and --end-chapter
  - suppression of BeautifulSoup XMLParsedAsHTMLWarning
  - automatic chunking of long chapters to avoid Edge TTS truncation
  - global parallel queue for chapter parts
  - default voice: en-US-AndrewNeural
  - default retries: 5

Parallel behavior:
  - Work is scheduled as individual TTS parts, not whole chapters.
  - Parts are still queued in reading order.
  - If chapter 40 has 20 parts, parts 1..20 are queued first.
  - With --parallel 3, parts 1,2,3 start first. When one finishes, part 4 starts, etc.
  - After chapter 40 part 20 is started, the queue moves to chapter 41 part 1.
  - After all parts are generated, parts are merged into chapter MP3s in book order.
  - Final M4B/M4A is also built in book order.

Examples:
    python speak.py "book.epub" --start-chapter 36 --m4b
    python speak.py "book.epub" --start-chapter 36 --parallel 3 --m4b
    python speak.py "book.epub" --start-chapter 36 --end-chapter 40 --parallel 3 --m4b
    python speak.py --list-voices

Requirements:
    pip install ebooklib beautifulsoup4 edge-tts lxml
    ffmpeg recommended for merging long chapter parts and required for --m4b / --m4a
"""

import argparse
import asyncio
import os
import re
import shutil
import subprocess
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def _bootstrap_runtime() -> None:
    """Make sure the backend dependencies are importable.

    A released CLI ships without a venv: the Python runtime tier is
    downloaded once (the same asset the desktop app uses) and this script
    re-runs itself with that interpreter. In a checkout with a prepared
    venv this is a no-op.
    """
    try:
        from core.bootstrap import backend_available, relaunch_with_runtime
    except Exception:
        return
    if backend_available():
        return
    if os.environ.get("SPEAK_EPUB_RUNTIME_ACTIVE") == "1":
        return  # already the runtime interpreter, nothing more to try
    relaunch_with_runtime()


_bootstrap_runtime()

try:
    import ebooklib
    from ebooklib import epub
    from bs4 import BeautifulSoup
    from bs4 import XMLParsedAsHTMLWarning
    import edge_tts
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("\nInstall with:")
    print("    pip install ebooklib beautifulsoup4 edge-tts lxml")
    print("\nOr download the self-contained CLI package (it downloads the")
    print("Python runtime on the first run).")
    sys.exit(1)

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

Chapter = tuple[int, str, str]
AudioEntry = tuple[int, str, str]

# Core delegation — single source of truth AD-1 (3.1/3.3 ratyfikacja brownfield)
# core/tts.py is pure Core-owned; speak.py delegates, does not duplicate.
from core.tts import PartJob, ChapterPlan
from core.tts import sanitize_filename as _core_sanitize
from core.tts import split_text_for_tts as _core_split_tts
from core.tts import build_generation_plan as _core_build_plan
from core.tts import tts_text_to_mp3 as _core_tts
from core.tts import run_part_jobs as _core_run
from core.tts import normalize_tts_rate as _core_norm_rate
from core.tts import ffmpeg_available as _core_ffmpeg
from core.tts import ffprobe_available as _core_ffprobe
from core.tts import concat_mp3_files as _core_concat
from core.tts import get_duration_ms as _core_dur
from core.tts import escape_ffmeta as _core_escape
from core.tts import finalize_chapter_audio as _core_finalize
from core.tts import build_m4b as _core_m4b
from core.tts import resolve_output_dir as _core_resolve_out

def sanitize_filename(value: str, fallback: str = "chapter", max_len: int = 60) -> str:
    return _core_sanitize(value, fallback, max_len)


def extract_chapters(epub_path: str, start_chapter: int = 1, end_chapter: Optional[int] = None) -> list[Chapter]:
    if start_chapter < 1:
        raise ValueError("--start-chapter must be 1 or greater")
    if end_chapter is not None and end_chapter < start_chapter:
        raise ValueError("--end-chapter cannot be smaller than --start-chapter")

    book = epub.read_epub(epub_path)
    chapters: list[Chapter] = []
    items_by_id = {item.id: item for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT)}
    extracted_chapter_number = 0
    skipped_near_empty = 0
    saw_content = False

    for item_id, _ in book.spine:
        item = items_by_id.get(item_id)
        if item is None:
            continue

        soup = BeautifulSoup(item.get_content(), "lxml")
        heading = soup.find(["h1", "h2", "h3"])
        title = heading.get_text(strip=True) if heading else item.get_name()

        for tag in soup(["script", "style", "nav", "aside"]):
            tag.decompose()

        text = soup.get_text(separator=" ", strip=True)
        text = re.sub(r"\s+", " ", text).strip()

        if len(text) > 100:
            saw_content = True
            extracted_chapter_number += 1
            if extracted_chapter_number < start_chapter:
                continue
            if end_chapter is not None and extracted_chapter_number > end_chapter:
                break
            chapters.append((extracted_chapter_number, title, text))
        else:
            skipped_near_empty += 1

    if skipped_near_empty:
        print(f"skipped {skipped_near_empty} near-empty spine item(s) (<100 chars: cover/TOC)")
    if not chapters and not saw_content:
        # M3: never silently yield nothing — but only when the book itself has
        # no usable content. When chapters exist yet the range excluded them
        # (e.g. --start-chapter past the end), return [] instead of
        # fabricating chapter 1 outside the requested range.
        longest: Chapter | None = None
        for item_id, _ in book.spine:
            item = items_by_id.get(item_id)
            if item is None:
                continue
            try:
                soup2 = BeautifulSoup(item.get_content(), "lxml")
                heading2 = soup2.find(["h1", "h2", "h3"])
                title2 = heading2.get_text(strip=True) if heading2 else item.get_name()
                for tag in soup2(["script", "style", "nav", "aside"]):
                    tag.decompose()
                text2 = re.sub(r"\s+", " ", soup2.get_text(separator=" ", strip=True)).strip()
            except Exception:
                continue
            if longest is None or len(text2) > len(longest[2]):
                longest = (1, title2, text2)
        if longest is not None and longest[2].strip():
            print(f"Warning: all spine items <100 chars — keeping longest ({len(longest[2])} chars) instead of empty output")
            chapters.append(longest)

    return chapters


def split_text_for_tts(text: str, max_chars: int = 3500) -> list[str]:
    return _core_split_tts(text, max_chars)


async def tts_text_to_mp3(
    text: str, output_path: str, voice: str, retries: int = 5, rate: str | None = None
) -> None:
    # Delegates to core/tts.py — single source, no duplication (Story 3.2)
    return await _core_tts(text, output_path, voice, retries=retries, rate=rate)


async def list_voices(all_languages: bool = False) -> None:
    voices = await edge_tts.list_voices()
    if not all_languages:
        voices = [v for v in voices if str(v.get("Locale", "")).startswith("en")]

    print(f"{'Name':<35} {'Gender':<8} {'Locale'}")
    print("-" * 60)
    for v in sorted(voices, key=lambda x: str(x.get("ShortName", ""))):
        print(f"{str(v.get('ShortName', '?')):<35} {str(v.get('Gender', '?')):<8} {str(v.get('Locale', '?'))}")

    if all_languages:
        print(f"\nTotal voices: {len(voices)}")
    else:
        print(f"\nTotal English voices: {len(voices)}")
        print("Use --all-languages to list voices for all languages.")


def ffmpeg_available() -> bool:
    return _core_ffmpeg()


def ffprobe_available() -> bool:
    return _core_ffprobe()


def concat_mp3_files(input_paths: list[str], output_path: str) -> None:
    return _core_concat(input_paths, output_path)


def get_duration_ms(path: str) -> int:
    return _core_dur(path)


def escape_ffmeta(s: str) -> str:
    return _core_escape(s)


def build_generation_plan(chapters: list[Chapter], output_dir: str, chunk_size: int, rate: str | None = None, dialogue_voice: str | None = None, migrate_titles: bool = False) -> tuple[list[ChapterPlan], list[PartJob]]:
    return _core_build_plan(chapters, output_dir, chunk_size, rate=rate, dialogue_voice=dialogue_voice, migrate_titles=migrate_titles)


async def run_part_jobs(
    jobs: list[PartJob],
    voice: str,
    parallel: int,
    retries: int,
    rate: str | None = None,
    engine: str = "edge",
    local_voice: str | None = None,
) -> None:
    # Delegates to core/tts.py — single source, no duplication (Story 3.2).
    # adaptive=True: concurrency self-tunes (grow on clean streaks, halve on retries).
    return await _core_run(
        jobs, voice, parallel, retries, rate=rate, adaptive=True, engine=engine, local_voice=local_voice
    )


def finalize_chapter_audio(plans: list[ChapterPlan], keep_parts: bool, normalize_audio: bool = False, trim_silence: bool = False) -> list[AudioEntry]:
    return _core_finalize(plans, keep_parts, normalize_audio=normalize_audio, trim_silence=trim_silence)


def build_m4b(output_dir: str, audio_entries: list[AudioEntry], book_title: str, ext: str = "m4b", bitrate: str = "48k", cover_path: str | None = None, artist: str | None = None) -> None:
    return _core_m4b(output_dir, audio_entries, book_title, ext, bitrate=bitrate, cover_path=cover_path, artist=artist)


def extract_cover_and_author(epub_path: str, output_dir: str) -> tuple[str | None, str | None]:
    """Best-effort (cover_path, author) from EPUB metadata. Never raises."""
    cover_path: str | None = None
    author: str | None = None
    try:
        book = epub.read_epub(epub_path)
    except Exception:
        return None, None
    try:
        md = book.get_metadata("DC", "creator")
        if md and md[0] and md[0][0]:
            author = str(md[0][0]).strip() or None
    except Exception:
        pass
    try:
        image_type = getattr(ebooklib, "ITEM_IMAGE", "image")
        for item in book.get_items():
            try:
                if item.get_type() != image_type:
                    continue
                name = f"{item.get_id() or ''} {item.get_name() or ''}".lower()
                if "cover" not in name:
                    continue
                blob = item.get_content()
                if not blob:
                    continue
                ext = ".jpg"
                if name.endswith(".png") or "png" in (item.get_media_type() or ""):
                    ext = ".png"
                cover_path = str(Path(output_dir) / f"cover{ext}")
                Path(cover_path).write_bytes(blob)
                break
            except Exception:
                continue
    except Exception:
        pass
    return cover_path, author


async def convert(
    epub_path: str,
    output_dir: str,
    voice: str,
    m4b: bool,
    m4a: bool,
    start_chapter: int = 1,
    end_chapter: Optional[int] = None,
    chunk_size: int = 3500,
    keep_parts: bool = False,
    parallel: int = 3,
    retries: int = 5,
    bitrate: str = "48k",
    rate: str = "+0%",
    engine: str = "auto",
    local_voice: str | None = None,
    dialogue_voice: str | None = None,
    normalize_audio: bool = False,
    trim_silence: bool = False,
    cuda: bool = False,
) -> None:
    try:
        chapters = extract_chapters(epub_path, start_chapter=start_chapter, end_chapter=end_chapter)
    except ValueError as e:
        print(f"Error: {e}")
        return

    if not chapters:
        print("No text chapters found in selected chapter range.")
        return

    # CWD-robust: unwritable CWD (e.g. System32) falls back to
    # ~/Documents/speak-epub instead of WinError 5 on makedirs.
    output_dir = str(_core_resolve_out(output_dir))
    os.makedirs(output_dir, exist_ok=True)
    total = len(chapters)

    print(f"Selected chapters: {start_chapter} to {'end' if end_chapter is None else end_chapter}")
    print(f"Found {total} chapter(s) in selected range.")
    print(f"Converting with voice: {voice}")
    print(f"Chunk size: {chunk_size} characters")
    if str(engine or "").strip().lower() == "local":
        print(f"Parallel TTS part jobs: {parallel} (local Piper: CPU cores, up to 8, no adaptive scaling)")
    else:
        from core.tts import ADAPTIVE_MAX_PARALLEL as _amp

        print(f"Parallel TTS part jobs: {parallel} (auto-tunes 1-{_amp} while running)")
    print(f"Retries per part: {retries}")
    # canonicalize CLI-style bare numbers ("15" -> "+15%") so --rate never
    # silently collapses to +0%: normalize_tts_rate requires the % sign.
    rate = _core_norm_rate(rate) if "%" in str(rate or "") else _core_norm_rate(f"{rate}%")
    print(f"Speech rate: {rate}")
    if engine and engine != "edge":
        suffix = f" ({local_voice})" if local_voice else ""
        print(f"TTS engine: {engine}{suffix}")
    if cuda:
        # the local engine may run on the GPU (onnxruntime-gpu); the flag is
        # honoured by core.tts_local, which falls back to the CPU
        os.environ["SPEAK_EPUB_PIPER_CUDA"] = "1"
        print("Local TTS engine: GPU (CUDA) requested — falls back to the CPU when unavailable")
    dialogue_voice = (dialogue_voice or "").strip() or None
    if dialogue_voice:
        print(f"Dialogue voice: {dialogue_voice}")
    if normalize_audio:
        print("Audio post-processing: loudness normalization on")
    if trim_silence:
        print("Audio post-processing: silence trimming on")
    print(f"Output folder: {output_dir}\n")

    # fail fast / warn upfront: truncation auto-repair, chapter merging and
    # M4B/M4A all need ffmpeg — better to know before hours of synthesis
    if not _core_ffmpeg():
        if str(engine or "").strip().lower() == "local":
            print("Error: the local TTS engine requires ffmpeg on PATH — install it and re-run.")
            return
        print("Warning: ffmpeg not found on PATH — chapter merging, M4B/M4A and truncation auto-repair are disabled.")

    # build identity: a changed rate/voice/engine must regenerate instead of
    # silently reusing wrong audio (returns True when wiped, plus fresh flag
    # for the one-time title-layout migration)
    from core.tts import check_build_identity as _check_ident

    _eng_norm = str(engine or "").strip().lower() or "auto"
    if _eng_norm not in ("auto", "edge", "local"):
        _eng_norm = "auto"
    _wiped, _fresh = _check_ident(
        output_dir,
        {
            "rate": rate,
            "voice": voice,
            "engine": _eng_norm,
            "local_voice": (local_voice or "").strip() or None,
            "dialogue_voice": dialogue_voice,
            "normalize_audio": bool(normalize_audio),
            "trim_silence": bool(trim_silence),
            # the spoken audio also depends on the chunk size and the source
            # book — a changed chunk size must regenerate instead of reusing
            # parts that were cut at a different boundary
            "chunk_size": int(chunk_size),
            "filters": "",
            "auto_boilerplate": False,
            "source": str(epub_path),
        },
    )

    cover_path, book_author = extract_cover_and_author(epub_path, output_dir)
    if cover_path:
        print(f"Cover art: {cover_path}")
    if book_author:
        print(f"Author: {book_author}")

    for chapter_number, title, text in chapters:
        chunks = split_text_for_tts(text, max_chars=chunk_size)
        display_title = title[:60] if title else f"Chapter {chapter_number}"
        print(f"Chapter {chapter_number:03d}: {display_title} - {len(text):,} chars, {len(chunks)} part(s)")

    plans, jobs = build_generation_plan(chapters, output_dir, chunk_size, rate=rate, dialogue_voice=dialogue_voice, migrate_titles=_fresh)
    print(f"\nQueued {len(jobs)} new TTS part job(s).")

    try:
        await run_part_jobs(
            jobs, voice=voice, parallel=parallel, retries=retries,
            rate=rate, engine=engine, local_voice=local_voice,
        )
    except Exception as e:
        print(f"\nERROR: generation failed: {e}")
        print("Already generated MP3 files are kept. Re-run the same command to resume.")
        raise

    audio_entries = finalize_chapter_audio(
        plans, keep_parts=keep_parts, normalize_audio=normalize_audio, trim_silence=trim_silence
    )
    print(f"\nDone! {len(audio_entries)} audio file(s)/entry saved to: {output_dir}")

    if m4b or m4a:
        base_book_title = sanitize_filename(Path(epub_path).stem, fallback="audiobook", max_len=120)
        if end_chapter is None:
            book_title = f"{base_book_title}_from_chapter_{start_chapter:03d}"
        else:
            book_title = f"{base_book_title}_chapters_{start_chapter:03d}_to_{end_chapter:03d}"
        ext = "m4a" if m4a else "m4b"
        print(f"M4B/M4A bitrate: {bitrate}")
        build_m4b(output_dir, audio_entries, book_title, ext, bitrate=bitrate, cover_path=cover_path, artist=book_author)


def main() -> None:
    parser = argparse.ArgumentParser(description="Speak EPUB: convert an EPUB file to an audiobook")
    parser.add_argument("epub", nargs="*", help="Path(s) to EPUB file(s) — several books convert sequentially, failures don't stop the queue")
    parser.add_argument("--voice", default="en-US-AndrewNeural", help="Edge TTS voice name. Default: en-US-AndrewNeural")
    parser.add_argument("--dialogue-voice", default="", help="Edge voice for quoted dialogue (narration keeps --voice). Empty: single voice. Edge engine only.")
    parser.add_argument("--output", default=None, help="Output folder name. Default: <epub_name>_audiobook")
    parser.add_argument("--m4b", action="store_true", help="Combine MP3s into a single M4B audiobook file. Requires ffmpeg.")
    parser.add_argument("--m4a", action="store_true", help="Combine MP3s into a single M4A audiobook file. Requires ffmpeg.")
    parser.add_argument("--list-voices", action="store_true", help="List available English TTS voices and exit")
    parser.add_argument("--all-languages", action="store_true", help="With --list-voices, show voices for all languages, not just English")
    parser.add_argument("--start-chapter", type=int, default=1, help="Start conversion from this extracted chapter number. Default: 1.")
    parser.add_argument("--end-chapter", type=int, default=None, help="Stop conversion after this extracted chapter number. Default: convert until the end.")
    parser.add_argument("--chunk-size", type=int, default=3500, help="Maximum characters per TTS request (Edge and local). Default: 3500. Lower if you still get truncation.")
    parser.add_argument("--keep-parts", action="store_true", help="Keep temporary part MP3 files after merging.")
    parser.add_argument("--parallel", type=int, default=3, help="Starting number of TTS parts generated at the same time (1-6). The pool auto-scales up to 12 while Edge TTS is not throttling, and backs off on retries. Default: 3.")
    parser.add_argument("--retries", type=int, default=5, help="Retries per TTS request/chunk. Default: 5.")
    parser.add_argument("--rate", default="+0%", help="Speech rate adjustment like +25%% or -10%% (clamped to ±100%%). Default: +0%%.")
    parser.add_argument("--engine", choices=["auto", "edge", "local"], default="auto", help="TTS engine: auto (local Piper on fast CPUs when the model is downloaded, else Edge), edge (cloud), local (offline Piper). Default: auto.")
    parser.add_argument("--local-voice", default="", help="Piper voice for the local engine, e.g. pl_PL-darkman-medium. Empty: default voice.")
    parser.add_argument("--bitrate", default="48k", help="M4B/M4A audio bitrate like 48k (16k-128k, speech default: 48k = the source bitrate).")
    parser.add_argument("--normalize-audio", action="store_true", help="Normalize chapter loudness (podcast levels) after merging.")
    parser.add_argument("--trim-silence", action="store_true", help="Trim leading/trailing silence of each chapter (dramatic pauses kept).")
    parser.add_argument(
        "--cuda",
        action="store_true",
        help="Run the local Piper engine on the GPU (needs onnxruntime-gpu; falls back to the CPU).",
    )

    args = parser.parse_args()

    if args.list_voices:
        asyncio.run(list_voices(all_languages=args.all_languages))
        return

    if not args.epub:
        parser.print_help()
        sys.exit(1)

    if len(args.epub) > 1 and args.output:
        print("Error: --output cannot be combined with multiple EPUB files (one folder per book).")
        sys.exit(1)

    if args.m4b and args.m4a:
        print("Error: use either --m4b or --m4a, not both.")
        sys.exit(1)

    if args.chunk_size < 500:
        print("Error: --chunk-size must be at least 500.")
        sys.exit(1)

    if args.chunk_size > 5000:
        # M3: Edge truncates overlong requests — fail loudly instead of silent gaps.
        print("Error: --chunk-size above 5000 truncates in Edge TTS (silent audio gaps). Use <=5000 (default 3500, try 2000 on truncation).")
        sys.exit(1)

    if args.parallel < 1:
        print("Error: --parallel must be at least 1.")
        sys.exit(1)

    if args.parallel > 6:
        print("Warning: --parallel above 6 is clamped to 6 (the adaptive pool can still scale up to 12 on its own).")

    if args.retries < 1:
        print("Error: --retries must be at least 1.")
        sys.exit(1)

    if not re.match(r"^\s*[+-]?\d+%?\s*$", str(args.rate or "")):
        print("Error: --rate must look like +0%, +25% or -10%.")
        sys.exit(1)

    local_voice_arg = (args.local_voice or "").strip() or None
    if local_voice_arg is not None:
        from core.tts_local import LOCAL_VOICES

        if local_voice_arg not in LOCAL_VOICES:
            print(f"Error: unknown --local-voice {local_voice_arg!r}. Available: {', '.join(LOCAL_VOICES)}")
            sys.exit(1)

    _bitrate_match = re.match(r"^(\d+)\s*k$", (args.bitrate or "").strip(), re.IGNORECASE)
    if not _bitrate_match or not (16 <= int(_bitrate_match.group(1)) <= 128):
        print("Error: --bitrate must be like 32k (16k-128k).")
        sys.exit(1)

    dialogue_voice_arg = (args.dialogue_voice or "").strip() or None

    failures: list[str] = []
    # CLI self-heal: try to repair before the per-book degraded-mode warnings
    # fire; with SPEAK_EPUB_FFMPEG_DIR or a prior install this is instant
    try:
        from core.ffmpeg_setup import ensure_ffmpeg

        ensure_ffmpeg(on_log=print)
    except Exception:
        pass
    for _idx, _epub_arg in enumerate(args.epub, 1):
        epub_path = Path(_epub_arg)
        if not epub_path.exists():
            print(f"File not found: {_epub_arg}")
            failures.append(_epub_arg)
            continue
        if len(args.epub) > 1:
            print(f"\n=== Book {_idx}/{len(args.epub)}: {_epub_arg} ===")
        output_dir = args.output or (epub_path.stem + "_audiobook")

        try:
            asyncio.run(
                convert(
                    str(epub_path),
                    output_dir,
                    args.voice,
                    args.m4b,
                    args.m4a,
                    start_chapter=args.start_chapter,
                    end_chapter=args.end_chapter,
                    chunk_size=args.chunk_size,
                    keep_parts=args.keep_parts,
                    parallel=args.parallel,
                    retries=args.retries,
                    bitrate=f"{int(_bitrate_match.group(1))}k",
                    # raw rate: convert() canonicalizes bare numbers ("25" -> "+25%")
                    rate=args.rate,
                    engine=args.engine,
                    local_voice=local_voice_arg,
                    dialogue_voice=dialogue_voice_arg,
                    normalize_audio=args.normalize_audio,
                    trim_silence=args.trim_silence,
                    cuda=args.cuda,
                )
            )
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as e:
            print(f"\nERROR converting {_epub_arg}: {e}")
            print("Already generated MP3 files are kept. Re-run the same command to resume.")
            failures.append(_epub_arg)

    if failures:
        print(f"\n{len(failures)} of {len(args.epub)} book(s) failed: {', '.join(failures)}")
        sys.exit(1)
    if len(args.epub) > 1:
        print(f"\nAll {len(args.epub)} book(s) converted successfully.")


if __name__ == "__main__":
    main()
