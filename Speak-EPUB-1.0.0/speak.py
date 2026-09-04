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
    sys.exit(1)

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

Chapter = tuple[int, str, str]
AudioEntry = tuple[int, str, str]

# Root vs inner path handling: when executed from project root, core lives in Speak-EPUB-1.0.0/core
if not (Path(__file__).resolve().parent / "core").is_dir():
    _candidate = Path(__file__).resolve().parent / "Speak-EPUB-1.0.0"
    if _candidate.is_dir() and str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

# Core delegation — single source of truth AD-1 (3.1/3.3 ratyfikacja brownfield)
# core/tts.py is pure Core-owned; speak.py delegates, does not duplicate.
from core.tts import PartJob, ChapterPlan
from core.tts import sanitize_filename as _core_sanitize
from core.tts import split_text_for_tts as _core_split_tts
from core.tts import build_generation_plan as _core_build_plan
from core.tts import tts_text_to_mp3 as _core_tts
from core.tts import run_part_jobs as _core_run
from core.tts import ffmpeg_available as _core_ffmpeg
from core.tts import ffprobe_available as _core_ffprobe
from core.tts import concat_mp3_files as _core_concat
from core.tts import get_duration_ms as _core_dur
from core.tts import escape_ffmeta as _core_escape
from core.tts import finalize_chapter_audio as _core_finalize
from core.tts import build_m4b as _core_m4b


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
            extracted_chapter_number += 1
            if extracted_chapter_number < start_chapter:
                continue
            if end_chapter is not None and extracted_chapter_number > end_chapter:
                break
            chapters.append((extracted_chapter_number, title, text))

    return chapters


def split_text_for_tts(text: str, max_chars: int = 3500) -> list[str]:
    return _core_split_tts(text, max_chars)


async def tts_text_to_mp3(text: str, output_path: str, voice: str, retries: int = 5) -> None:
    # Delegates to core/tts.py — single source, no duplication (Story 3.2)
    return await _core_tts(text, output_path, voice, retries=retries)


async def list_voices(all_languages: bool = False) -> None:
    voices = await edge_tts.list_voices()
    if not all_languages:
        voices = [v for v in voices if v["Locale"].startswith("en")]

    print(f"{'Name':<35} {'Gender':<8} {'Locale'}")
    print("-" * 60)
    for v in sorted(voices, key=lambda x: x["ShortName"]):
        print(f"{v['ShortName']:<35} {v['Gender']:<8} {v['Locale']}")

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


def build_generation_plan(chapters: list[Chapter], output_dir: str, chunk_size: int) -> tuple[list[ChapterPlan], list[PartJob]]:
    return _core_build_plan(chapters, output_dir, chunk_size)


async def run_part_jobs(jobs: list[PartJob], voice: str, parallel: int, retries: int) -> None:
    # Delegates to core/tts.py — single source, no duplication (Story 3.2)
    return await _core_run(jobs, voice, parallel, retries)


def finalize_chapter_audio(plans: list[ChapterPlan], keep_parts: bool) -> list[AudioEntry]:
    return _core_finalize(plans, keep_parts)


def build_m4b(output_dir: str, audio_entries: list[AudioEntry], book_title: str, ext: str = "m4b", bitrate: str = "32k") -> None:
    return _core_m4b(output_dir, audio_entries, book_title, ext, bitrate=bitrate)


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
    bitrate: str = "32k",
) -> None:
    try:
        chapters = extract_chapters(epub_path, start_chapter=start_chapter, end_chapter=end_chapter)
    except ValueError as e:
        print(f"Error: {e}")
        return

    if not chapters:
        print("No text chapters found in selected chapter range.")
        return

    os.makedirs(output_dir, exist_ok=True)
    total = len(chapters)

    print(f"Selected chapters: {start_chapter} to {'end' if end_chapter is None else end_chapter}")
    print(f"Found {total} chapter(s) in selected range.")
    print(f"Converting with voice: {voice}")
    print(f"Chunk size: {chunk_size} characters")
    print(f"Parallel TTS part jobs: {parallel}")
    print(f"Retries per part: {retries}")
    print(f"Output folder: {output_dir}\n")

    for chapter_number, title, text in chapters:
        chunks = split_text_for_tts(text, max_chars=chunk_size)
        display_title = title[:60] if title else f"Chapter {chapter_number}"
        print(f"Chapter {chapter_number:03d}: {display_title} - {len(text):,} chars, {len(chunks)} part(s)")

    plans, jobs = build_generation_plan(chapters, output_dir, chunk_size)
    print(f"\nQueued {len(jobs)} new TTS part job(s).")

    try:
        await run_part_jobs(jobs, voice=voice, parallel=parallel, retries=retries)
    except Exception as e:
        print(f"\nERROR: generation failed: {e}")
        print("Already generated MP3 files are kept. Re-run the same command to resume.")
        raise

    audio_entries = finalize_chapter_audio(plans, keep_parts=keep_parts)
    print(f"\nDone! {len(audio_entries)} audio file(s)/entry saved to: {output_dir}")

    if m4b or m4a:
        base_book_title = sanitize_filename(Path(epub_path).stem, fallback="audiobook", max_len=120)
        if end_chapter is None:
            book_title = f"{base_book_title}_from_chapter_{start_chapter:03d}"
        else:
            book_title = f"{base_book_title}_chapters_{start_chapter:03d}_to_{end_chapter:03d}"
        ext = "m4a" if m4a else "m4b"
        print(f"M4B/M4A bitrate: {bitrate}")
        build_m4b(output_dir, audio_entries, book_title, ext, bitrate=bitrate)


def main() -> None:
    parser = argparse.ArgumentParser(description="Speak EPUB: convert an EPUB file to an audiobook")
    parser.add_argument("epub", nargs="?", help="Path to the EPUB file")
    parser.add_argument("--voice", default="en-US-AndrewNeural", help="Edge TTS voice name. Default: en-US-AndrewNeural")
    parser.add_argument("--output", default=None, help="Output folder name. Default: <epub_name>_audiobook")
    parser.add_argument("--m4b", action="store_true", help="Combine MP3s into a single M4B audiobook file. Requires ffmpeg.")
    parser.add_argument("--m4a", action="store_true", help="Combine MP3s into a single M4A audiobook file. Requires ffmpeg.")
    parser.add_argument("--list-voices", action="store_true", help="List available English TTS voices and exit")
    parser.add_argument("--all-languages", action="store_true", help="With --list-voices, show voices for all languages, not just English")
    parser.add_argument("--start-chapter", type=int, default=1, help="Start conversion from this extracted chapter number. Default: 1.")
    parser.add_argument("--end-chapter", type=int, default=None, help="Stop conversion after this extracted chapter number. Default: convert until the end.")
    parser.add_argument("--chunk-size", type=int, default=3500, help="Maximum characters per Edge TTS request. Default: 3500. Lower if you still get truncation.")
    parser.add_argument("--keep-parts", action="store_true", help="Keep temporary part MP3 files after merging.")
    parser.add_argument("--parallel", type=int, default=3, help="Number of TTS parts to generate at the same time. Recommended: 2 or 3. Default: 3.")
    parser.add_argument("--retries", type=int, default=5, help="Retries per TTS request/chunk. Default: 5.")
    parser.add_argument("--bitrate", default="32k", help="M4B/M4A audio bitrate like 32k (16k-128k, speech default: 32k).")

    args = parser.parse_args()

    if args.list_voices:
        asyncio.run(list_voices(all_languages=args.all_languages))
        return

    if not args.epub:
        parser.print_help()
        sys.exit(1)

    epub_path = Path(args.epub)
    if not epub_path.exists():
        print(f"File not found: {epub_path}")
        sys.exit(1)

    if args.m4b and args.m4a:
        print("Error: use either --m4b or --m4a, not both.")
        sys.exit(1)

    if args.chunk_size < 500:
        print("Error: --chunk-size must be at least 500.")
        sys.exit(1)

    if args.parallel < 1:
        print("Error: --parallel must be at least 1.")
        sys.exit(1)

    if args.parallel > 6:
        print("Warning: high --parallel values may trigger Edge TTS throttling. Recommended: 2 or 3.")

    if args.retries < 1:
        print("Error: --retries must be at least 1.")
        sys.exit(1)

    _bitrate_match = re.match(r"^(\d+)\s*k$", (args.bitrate or "").strip(), re.IGNORECASE)
    if not _bitrate_match or not (16 <= int(_bitrate_match.group(1)) <= 128):
        print("Error: --bitrate must be like 32k (16k-128k).")
        sys.exit(1)

    output_dir = args.output or (epub_path.stem + "_audiobook")

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
        )
    )


if __name__ == "__main__":
    main()
