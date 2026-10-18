"""
core/tts.py — TTS Chunking + PartJob queue (Story 3.1 ratyfikacja brownfield).

AD-1: GUI→Core→Port→Adapter — this module is pure Core-owned single source.
AD-8: EPUB as intermediate invariant; TTS reads only EPUB via extract_chapters.
AD-2: raw never filtered; no filtering here.

Ratifies speak.py semantics:
- split_text_for_tts 3500 sentence-boundary r"(?<=[.!?;:])\\s+" + hard-cut fallback >3500
- PartJob frozen dataclass with chapter_title retained for speak.py compat
- build_generation_plan global queue reading-order ch40 p1..20 before ch41 p1
- sanitize_filename mirror speak.py:84 (no epub extra fallback)

Pure: only os/re/dataclasses/pathlib/typing — no adapters/*, no speak.
Subprocess (shutil/subprocess) is used exclusively for ffmpeg/ffprobe
invocations: local encoding, merging, M4B/M4A and post-processing.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

Chapter = Tuple[int, str, str]
AudioEntry = Tuple[int, str, str]

RESUME_LOCK_NAME = ".tts_resume.lock"
RESUME_LOCK_STALE_SEC = 600


def _resume_root_for_jobs(jobs: List[PartJob]) -> Optional[Path]:
    """Best-effort output root for the resume lock (handles _parts layout)."""
    try:
        if not jobs:
            return None
        raw = getattr(jobs[0], "output_path", None)
        if not isinstance(raw, str) or not raw.strip():
            return None
        p = Path(raw)
        # multi-part jobs live in <root>/_parts/ — lock the root, not _parts
        if p.parent.name == "_parts":
            return p.parent.parent
        return p.parent
    except Exception:
        return None


def acquire_resume_lock(root: Any, _attempt: int = 0) -> Optional[Path]:
    """Best-effort inter-process guard against concurrent resume runs (H6).

    Creates <root>/.tts_resume.lock with O_EXCL. Returns lock path on
    success, None when the root cannot be determined. Raises RuntimeError
    when a fresh lock already exists (another run is active). Stale locks
    (>10 min) are reclaimed.
    """
    if _attempt > 3:
        # a rival process is cycling the lock file — stop instead of recursing
        raise RuntimeError("resume lock acquisition unstable (lockfile cycling)")
    try:
        base = Path(str(root)) if root is not None else None
    except Exception:
        return None
    if base is None:
        return None
    try:
        base.mkdir(parents=True, exist_ok=True)
    except Exception:
        return None
    lock = base / RESUME_LOCK_NAME
    try:
        import time as _time

        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            os.write(fd, str(os.getpid()).encode("utf-8", "ignore"))
        except Exception:
            pass
        finally:
            try:
                os.close(fd)
            except Exception:
                pass
        return lock
    except FileExistsError:
        try:
            import time as _time

            try:
                age = _time.time() - lock.stat().st_mtime
            except FileNotFoundError:
                # lock vanished between open failure and stat (process exit
                # race) — just retry the acquisition once.
                return acquire_resume_lock(base, _attempt + 1)
            if age > RESUME_LOCK_STALE_SEC:
                try:
                    lock.unlink(missing_ok=True)
                except OSError:
                    # unlink failed (permissions?) — do NOT recurse, or a
                    # permanently undeletable lockfile becomes RecursionError.
                    # Fall through to the concurrent-run error below.
                    pass
                else:
                    return acquire_resume_lock(base, _attempt + 1)
        except Exception:
            pass
        raise RuntimeError(
            f"concurrent resume detected: {lock} exists — "
            "another conversion is already writing this output dir"
        )
    except OSError:
        return None


def release_resume_lock(lock: Any) -> None:
    try:
        if lock is None:
            return
        Path(str(lock)).unlink(missing_ok=True)
    except Exception:
        pass


def sanitize_filename(value: str, fallback: str = "chapter", max_len: int = 60) -> str:
    """
    Mirror speak.py:84 sanitize_filename.

    - replace [\\/:*?"<>|] with _
    - collapse whitespace
    - truncate max_len
    - fallback if empty
    NOTE: intentionally keeps speak.py behaviour where "///" -> "___"
    (epub.py falls back to "chapter" here — historic divergence, deferred).
    """
    if not isinstance(value, str):
        value = str(value) if value is not None else ""
    safe = re.sub(r'[\\/:*?"<>|]', "_", value).strip()
    safe = re.sub(r"\s+", " ", safe).strip()
    safe = safe[:max_len].strip()
    return safe or fallback


def user_output_base() -> Path:
    """User-writable base directory for app output (EPUB/audiobook files).

    Used when the process working directory is not writable — e.g. the GUI
    exe launched with CWD=C:\\Windows\\System32, where creating ./output
    dies with WinError 5 (Access is denied).
    """
    home = Path.home()
    if os.name == "nt":
        return home / "Documents" / "speak-epub"
    return home / "speak-epub"


def _is_writable(path: Path) -> bool:
    """os.access probe, isolated as a seam so tests can simulate a denied CWD."""
    try:
        return os.access(path, os.W_OK)
    except Exception:
        return False


def _abspath(path: Path) -> Path:
    try:
        return path.resolve()
    except Exception:
        return path


def _seems_usable_dir(path: Path) -> bool:
    """True if path exists as dir or its nearest existing ancestor is writable.

    Pure probe — creates nothing, so an unwritable location (e.g.
    C:\\Windows\\System32) is never touched, only inspected.
    """
    try:
        probe = path
        while not probe.exists():
            parent = probe.parent
            if parent == probe:
                return False
            probe = parent
        return probe.is_dir() and _is_writable(probe)
    except Exception:
        return False


def resolve_output_dir(
    output_dir: Any = None, dirname: str = "output", ensure: bool = True
) -> Path:
    """Resolve an output directory to an absolute, writable path.

    - explicit absolute path → returned as-is (explicit choice wins; the
      caller creates it and surfaces the real error if it is bad)
    - explicit relative path or default `dirname` → anchored at the process
      working directory (CLI compat: ./output next to where you run it),
      but only when that location probes writable — an unwritable CWD
      (e.g. GUI exe launched from C:\\Windows\\System32) is never touched,
      no mkdir is ever attempted there
    - otherwise falls back to user_output_base()/dirname and prints where
      the files actually go (stdout is sidecar-safe: heartbeat lines already
      flow through it, and both build_epub/build_audio return absolute paths)
    - ensure=False performs no filesystem writes; picks the cwd-anchored dir
      when it seems usable, else the fallback (for read-only status probes)

    Raises the underlying OSError only when nothing is writable.
    """
    if isinstance(output_dir, Path):
        raw = str(output_dir).strip() or dirname
    elif isinstance(output_dir, str):
        raw = output_dir.strip() or dirname
    elif output_dir is None:
        raw = dirname
    else:
        try:
            raw = str(output_dir).strip() or dirname
        except Exception:
            raw = dirname

    cand = Path(raw)
    if cand.is_absolute():
        if ensure:
            cand.mkdir(parents=True, exist_ok=True)
        return _abspath(cand)

    try:
        anchored = Path.cwd() / cand
    except Exception:
        anchored = None
    if anchored is not None and _seems_usable_dir(anchored):
        if not ensure:
            return _abspath(anchored)
        try:
            anchored.mkdir(parents=True, exist_ok=True)
            return _abspath(anchored)
        except OSError:
            pass  # lost race or ACL quirk between probe and mkdir → fallback
    fallback = user_output_base() / dirname
    if ensure:
        fallback.mkdir(parents=True, exist_ok=True)
    if anchored is not None:
        print(f"output directory not usable: {anchored} — using {fallback} instead")
    return _abspath(fallback)


@dataclass(frozen=True)
class PartJob:
    chapter_number: int
    chapter_title: str
    part_number: int
    part_count: int
    text: str
    output_path: str
    is_final_chapter_file: bool
    #: Edge voice override for this part (dialogue in a second voice);
    #: None = the run's voice. Ignored by the local engine.
    voice: Optional[str] = None
    #: Seconds of silence appended to this part after synthesis (1.0 s pause
    #: after a chapter-title part). 0 = none.
    append_silence_sec: float = 0.0


@dataclass
class ChapterPlan:
    chapter_number: int
    title: str
    chapter_mp3: str
    part_paths: List[str]
    marker_entries_if_unmerged: List[AudioEntry]
    #: Title part path (1 s pause appended) merged ahead of part_paths;
    #: None = legacy layout (no title part). Never deleted by keep_parts.
    title_part_path: Optional[str] = None


# ---------------------------------------------------------------------------
# Part-audio verification (anti-gap gate).
#
# Root cause of skipped fragments in finished audiobooks: Edge TTS silently
# truncates overlong requests, and the resume logic treated ANY existing file
# as done — so a truncated part was skipped forever and the merge kept the gap.
# Every gate below (fresh save, resume skip, plan guard) now validates.
# ---------------------------------------------------------------------------

#: Files smaller than this are partial writes, never valid speech.
MIN_PART_BYTES = 1024

#: Baseline speech rate used to derive the minimum plausible duration.
#: Neural voices read ~13-16 chars/s; 15 is the conservative middle.
EXPECTED_TTS_CPS = 15.0

#: Actual duration must reach at least this fraction of the expected duration.
#: 0.5 at 15 cps == effective floor of 7.5 chars/s — far below any natural
#: rate, so false positives only cost one re-fetch while real truncations
#: (typically <50% of the text) are caught.
MIN_DURATION_RATIO = 0.5

#: Duration check applies only to chunks of at least this length; tiny chunks
#: get the size check only (ffprobe rounding would dominate).
MIN_TEXT_LEN_FOR_DURATION_CHECK = 50


class _TruncatedPartError(RuntimeError):
    """Internal: Edge TTS returned a complete-but-short file (deterministic)."""


_RE_TTS_RATE = re.compile(r"^\s*([+-]?)\s*(\d+)\s*%\s*$")


def normalize_tts_rate(value: Any, default: str = "+0%") -> str:
    """Normalize a speech-rate like '+25%'/'-30%' (clamped to ±100).

    Accepts '+15%', '15%', '-30%', 15 → '+15%'. Garbage returns `default`.
    Edge TTS requires the sign, so the result always carries one.
    """
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        value = f"{int(value):+d}%"
    if not isinstance(value, str):
        return default
    m = _RE_TTS_RATE.match(value)
    if not m:
        return default
    num = int(m.group(2))
    if m.group(1) == "-":
        num = -num
    num = max(-100, min(100, num))
    return f"{num:+d}%"


def _part_file_valid_quick(path: str) -> bool:
    """Pure size gate for build_generation_plan (no subprocess, keeps it pure)."""
    try:
        return os.path.isfile(path) and os.path.getsize(path) >= MIN_PART_BYTES
    except OSError:
        return False


def _ensure_valid_or_drop(path: str, text: Optional[str], label: str, rate: Optional[str] = None) -> bool:
    """Plan-guard helper: an existing file counts as done only if it verifies.

    A stale truncated/merged-with-gaps file is deleted so its parts get
    re-queued (resume heals instead of reusing the gap). Returns True when
    the file exists and is valid.
    """
    if not _part_file_valid_quick(path):
        return False
    ok, reason = verify_part_audio(path, text, rate=rate)
    if ok:
        return True
    try:
        Path(path).unlink(missing_ok=True)
    except Exception:
        pass
    print(f"{label}: existing file invalid ({reason}), re-generating")
    return False


def verify_part_audio(path: str, text: Optional[str] = None, rate: Optional[str] = None) -> Tuple[bool, str]:
    """Check a generated part MP3 is complete, not truncated.

    Returns (ok, reason) with reason in:
    missing | too_small | no_duration | truncated | ok | ok_no_duration_check.

    The duration check needs text + ffprobe; without either only the size
    gate applies (still catches empty/partial writes).

    `rate` (Edge-style '+25%') scales the minimum-duration floor down for
    faster speech: at +100% the audio is ~half as long, so an unscaled
    MIN_DURATION_RATIO would flag a complete fast part as truncated.
    Slower rates (negative) never shorten audio, so the nominal floor
    stays — it can only pass, never false-positive.
    """
    try:
        if not os.path.isfile(path):
            return False, "missing"
        if os.path.getsize(path) < MIN_PART_BYTES:
            return False, "too_small"
    except OSError:
        return False, "missing"

    if text is None or len(text) < MIN_TEXT_LEN_FOR_DURATION_CHECK:
        return True, "ok_no_duration_check"
    if not ffprobe_available():
        return True, "ok_no_duration_check"
    try:
        duration_ms = get_duration_ms(path)
    except Exception:
        return True, "ok_no_duration_check"
    if duration_ms <= 0:
        return False, "no_duration"
    speed = 1.0
    if rate is not None:
        try:
            _num = int(normalize_tts_rate(rate).rstrip("%"))
            if _num > 0:
                speed = 1.0 + min(_num, 100) / 100.0
        except Exception:
            speed = 1.0
    min_expected_ms = len(text) * 1000.0 / EXPECTED_TTS_CPS * MIN_DURATION_RATIO / speed
    if duration_ms < min_expected_ms:
        return False, "truncated"
    return True, "ok"


def split_text_for_tts(text: str, max_chars: int = 3500) -> List[str]:
    """
    Sentence-boundary chunking with hard-cut fallback.

    - whitespace collapse re.sub r"\\s+" then strip
    - split at (?<=[.!?;:])\\s+
    - current flush, len(sentence)>max_chars -> hard cut while start
    - all chunks <=max_chars, order preserved via chunks.append
    """
    if not isinstance(max_chars, int) or max_chars < 1:
        raise ValueError("max_chars must be a positive integer")
    if max_chars > 5000:
        print(f"Warning: max_chars={max_chars} > 5000 truncates in Edge TTS — consider 2000-3500")
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


#: Pause (s) between a chapter-title part and the chapter body. The title is
#: synthesized as its own leading part and this silence is appended to it,
#: so listeners hear "Chapter title … <pause> … text" instead of one run-on.
TITLE_PAUSE_SEC = 1.0

#: Dialogue splitter: Polish „…" (either typographic close), straight "…",
#: «…», ‹…› (DOTALL, non-greedy). Unmatched quotes stay narration — never
#: lose or mislabel text.
_DIALOGUE_RE = re.compile(r"(„.+?[“”]|\".+?\"|«.+?»|‹.+?›)", re.DOTALL)


def split_dialogue(text: str) -> List[Tuple[str, bool]]:
    """Split text into (segment, is_dialogue) at quotation marks.

    Returns [(text, False)] untouched when there are no quotes. Segments
    cover the whole input (only whitespace-only pieces are dropped, which
    chunking would collapse anyway).
    """
    out: List[Tuple[str, bool]] = []
    pos = 0
    for m in _DIALOGUE_RE.finditer(text or ""):
        if m.start() > pos:
            out.append((text[pos:m.start()], False))
        out.append((m.group(0), True))
        pos = m.end()
    if pos < len(text or ""):
        out.append((text[pos:], False))
    if not out:
        return [(text, False)] if (text or "").strip() else []
    return [(s, d) for s, d in out if s.strip()]


def split_title_body(title: Optional[str], text: str) -> Tuple[Optional[str], str]:
    """Split a leading chapter title off the body text.

    Returns (title_text_or_None, body_text). The title is split off only when
    the body actually starts with it (normalized comparison) — otherwise the
    title is returned as None and the text is untouched, so no new audio is
    ever invented and nothing is ever read twice.
    """
    body = (text or "").strip()
    t = (title or "").strip()
    if not t or not body:
        return None, body
    norm = lambda s: re.sub(r"\s+", " ", s).strip()
    title_n, body_n = norm(t), norm(body)
    if body_n.startswith(title_n):
        rest = body_n[len(title_n):].lstrip(" .:;-–—")
        if rest:
            return t, rest
    return None, body


def ensure_pause_file(part_dir: str, seconds: float = TITLE_PAUSE_SEC) -> Optional[str]:
    """Path to a silence MP3 (24 kHz mono, like part files), generating it once.

    Returns None when ffmpeg is unavailable or generation fails — callers
    then skip the pause instead of failing the build.
    """
    if not ffmpeg_available():
        return None
    try:
        name = f"_pause_{seconds:g}s.mp3"
    except Exception:
        return None
    path = os.path.join(part_dir, name)
    try:
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            return path
    except OSError:
        pass
    try:
        os.makedirs(part_dir, exist_ok=True)
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return None
        subprocess.run(
            [
                ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                "-t", str(float(seconds)),
                "-codec:a", "libmp3lame", "-b:a", "32k", "-ac", "1", "-ar", "24000",
                path,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **subprocess_kwargs(),
        )
    except Exception:
        return None
    try:
        return path if os.path.isfile(path) else None
    except OSError:
        return None


def _append_silence(part_path: str, pause_path: str) -> None:
    """Append a silence MP3 to a part file, atomically (tmp + replace)."""
    tmp = part_path + ".pausetmp"
    try:
        concat_mp3_files([part_path, pause_path], tmp)
        os.replace(tmp, part_path)
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass


#: Build-identity manifest: records the synthesis params an output directory
#: was generated with, so a later run with different params regenerates
#: instead of silently reusing wrong audio (rate/voice/engine changes).
BUILD_IDENTITY_FILENAME = ".speak-epub-build.json"

#: Manifest schema/layout version. Bump when artifact semantics change
#: (v2: title parts + pause; v3: repaired trim filter — old outputs may
#: have been over-trimmed by the broken silenceremove chain). A mismatch
#: wipes and rebuilds like any change.
BUILD_IDENTITY_VERSION = 3

#: Params that define generated audio. A change in any of them invalidates
#: existing part/chapter files (different speed, voice, engine, processing).
BUILD_IDENTITY_KEYS = (
    "rate",
    "voice",
    "engine",
    "local_voice",
    "dialogue_voice",
    "normalize_audio",
    "trim_silence",
)


def check_build_identity(
    audio_dir: str, identity: Dict[str, Any], on_log: Optional[Callable[[str], None]] = None
) -> Tuple[bool, bool]:
    """Ensure the build manifest matches; returns (wiped, fresh).

    - no manifest yet → write it, report fresh=True (caller migrates
      title-split chapters once); existing files are grandparented, not wiped
    - params match → (False, False), pure resume
    - params differ → delete generated artifacts (_parts/*.mp3, chapter
      *.mp3, *.m4b/*.m4a in this dir), rewrite the manifest, report wiped
    A manifest that cannot be read/written degrades to (False, False) with
    a warning — never wipe what cannot be recorded.
    """

    def _log(msg: str) -> None:
        if on_log:
            try:
                on_log(msg)
            except Exception:
                pass
        else:
            print(msg)

    manifest = os.path.join(audio_dir, BUILD_IDENTITY_FILENAME)
    wanted = {k: identity.get(k) for k in BUILD_IDENTITY_KEYS}
    wanted["plan"] = BUILD_IDENTITY_VERSION
    try:
        os.makedirs(audio_dir, exist_ok=True)
    except OSError:
        pass
    try:
        with open(manifest, "r", encoding="utf-8") as f:
            stored = json.load(f)
    except Exception:
        stored = None
    if not isinstance(stored, dict):
        try:
            with open(manifest, "w", encoding="utf-8") as f:
                json.dump(wanted, f, ensure_ascii=False, indent=2)
        except OSError as e:
            _log(f"warning: cannot write build manifest: {e}")
            return False, False
        return False, True
    same = all(stored.get(k) == v for k, v in wanted.items())
    if same:
        return False, False
    # record the new identity BEFORE wiping: never wipe what cannot be
    # recorded — a failed manifest write leaves the old audio intact
    try:
        with open(manifest, "w", encoding="utf-8") as f:
            json.dump(wanted, f, ensure_ascii=False, indent=2)
    except OSError as e:
        _log(f"warning: cannot write build manifest: {e}")
        return False, False
    # params changed: wipe generated audio so it regenerates with the new ones
    wiped: List[str] = []
    try:
        parts_dir = os.path.join(audio_dir, "_parts")
        if os.path.isdir(parts_dir):
            for name in os.listdir(parts_dir):
                if name.lower().endswith(".mp3"):
                    try:
                        os.remove(os.path.join(parts_dir, name))
                        wiped.append(name)
                    except OSError:
                        pass
        for name in os.listdir(audio_dir):
            low = name.lower()
            if low.endswith((".mp3", ".m4b", ".m4a")) and os.path.isfile(os.path.join(audio_dir, name)):
                try:
                    os.remove(os.path.join(audio_dir, name))
                    wiped.append(name)
                except OSError:
                    pass
    except OSError as e:
        _log(f"warning: build identity wipe failed: {e}")
        return True, False
    changed = sorted({f"{k}: {stored.get(k)!r} -> {v!r}" for k, v in wanted.items() if stored.get(k) != v})
    _log(f"build parameters changed ({'; '.join(changed)}) — regenerating {len(wiped)} audio file(s)")
    return True, False


def postprocess_chapter_file(path: str, normalize_audio: bool = False, trim_silence: bool = False) -> bool:
    """Apply loudness normalization and/or silence trimming in place.

    Loudness: single-pass loudnorm (podcast levels). Silence: only long
    leading/trailing silence (>~2 s) is trimmed; natural speech pauses and
    the post-title pause survive intact. Returns True when the file was
    re-encoded. Never raises: failures warn and leave the original file
    untouched.
    """
    if not (normalize_audio or trim_silence):
        return False
    if not ffmpeg_available():
        print("Warning: audio post-processing needs ffmpeg on PATH — skipping.")
        return False
    filters: List[str] = []
    if normalize_audio:
        filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")
    if trim_silence:
        # this build's silenceremove stop_periods removes ALL silence >= the
        # threshold anywhere in the stream (verified against ffmpeg 8.0), so
        # trim trailing by reversing the stream and reusing leading-trim.
        trim_lead = (
            "silenceremove=start_periods=1:start_duration=0:"
            "start_silence=2.0:start_threshold=-60dB"
        )
        filters.append(f"{trim_lead},areverse,{trim_lead},areverse")
    try:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return False
        tmp = path + ".postmp"
        subprocess.run(
            [
                ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-i", path,
                "-codec:a", "libmp3lame", "-b:a", "32k", "-ac", "1", "-ar", "24000",
                "-af", ",".join(filters),
                "-f", "mp3",
                tmp,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **subprocess_kwargs(),
        )
        os.replace(tmp, path)
        return True
    except Exception as e:
        print(f"Warning: audio post-processing failed for {Path(path).name} ({e}) — keeping original.")
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return False


def build_generation_plan(
    chapters: List[Chapter],
    output_dir: str,
    chunk_size: int,
    rate: Optional[str] = None,
    dialogue_voice: Optional[str] = None,
    migrate_titles: bool = False,
) -> Tuple[List[ChapterPlan], List[PartJob]]:
    """
    Build global PartJob queue in reading order.

    - for chapter in chapters: for part in chunks: queue.append(PartJob)
    - ch40 p1..20 entirely before ch41 p1
    - sanitize title via sanitize_filename
    - output paths: f"{chapter_number:03d}_{safe}_part{part_number:03d}.mp3" in _parts for multi
      single-chunk "{chapter_number:03d}_{safe}.mp3" with is_final_chapter_file=True
    - guard: an existing chapter/part file re-queues unless it verifies
      (_ensure_valid_or_drop: size gate + duration vs text when ffprobe is
      available), so truncated/partial files are regenerated instead of
      skipped forever; single-chunk guard applies to chapter_mp3 directly
    - `rate` scales the guard's duration floor for faster speech, so resume
      at high rates does not mistake complete fast files for truncation
    - chapter titles are synthesized as their own leading part
      (`{nnn}_{safe}.title.mp3` beside the chapter file) with a 1 s pause
      appended — but only when the title is already read as part of the
      text (normalized prefix match) and ffmpeg is available; otherwise the
      legacy layout is kept byte-for-byte. Body part numbering never
      changes, so existing part files stay resume-compatible. When the title
      is split off, the stale first body part (title audio baked in) is
      re-queued — on `migrate_titles` (first run with a build manifest) it
      is deleted outright since duration checks cannot tell it apart
    - `dialogue_voice`: quoted dialogue segments (Polish „…", "…", «…», ‹…›)
      become their own part jobs with a voice override (Edge engine only);
      narration keeps the run voice. Without it the plan is unchanged
    - ChapterPlan mirror speak.py:75
    - empty chunks -> plan with [],[] and no jobs
    I/O only (os + ffprobe resume validation), no edge_tts.
    """
    plans: List[ChapterPlan] = []
    jobs: List[PartJob] = []
    # CWD-robust: a relative output dir under an unwritable CWD (GUI exe
    # launched from System32) resolves to the user fallback instead of
    # dying later in makedirs with WinError 5.
    output_dir = str(resolve_output_dir(output_dir))
    part_dir = os.path.join(output_dir, "_parts")
    dlg_voice = dialogue_voice.strip() if isinstance(dialogue_voice, str) and dialogue_voice.strip() else None
    can_pause = ffmpeg_available()

    for chapter_number, title, text in chapters:
        safe_title = sanitize_filename(title, fallback=f"Chapter_{chapter_number:03d}")
        chapter_mp3 = os.path.join(output_dir, f"{chapter_number:03d}_{safe_title}.mp3")

        # 1 s title pause: split a leading title off the body. Only when the
        # title is actually read as part of the text — never invent audio.
        title_text: Optional[str] = None
        body_text = text
        if can_pause:
            title_text, body_text = split_title_body(title, text)

        # dialogue segmentation per body (narration keeps the run voice)
        segments = split_dialogue(body_text) if dlg_voice else [(body_text, False)]
        pieces: List[Tuple[str, Optional[str]]] = []
        for seg_text, is_dlg in segments:
            for chunk in split_text_for_tts(seg_text, max_chars=chunk_size):
                pieces.append((chunk, dlg_voice if (is_dlg and dlg_voice) else None))

        label = f"Chapter {chapter_number:03d}"
        if not pieces and title_text is None:
            plans.append(ChapterPlan(chapter_number, title, chapter_mp3, [], []))
            continue

        # Legacy single-chunk fast path: no title, one body piece -> the
        # chapter file IS the part (works without ffmpeg, resume-stable).
        if title_text is None and len(pieces) == 1:
            chunk_text, chunk_voice = pieces[0]
            plans.append(
                ChapterPlan(chapter_number, title, chapter_mp3, [chapter_mp3], [(chapter_number, title, chapter_mp3)])
            )
            if not _ensure_valid_or_drop(chapter_mp3, chunk_text, label, rate=rate):
                jobs.append(
                    PartJob(
                        chapter_number=chapter_number,
                        chapter_title=title,
                        part_number=1,
                        part_count=1,
                        text=chunk_text,
                        output_path=chapter_mp3,
                        is_final_chapter_file=True,
                        voice=chunk_voice,
                    )
                )
            continue

        # Title + multi-piece layout: title part beside the chapter file,
        # body parts numbered exactly as before (resume-compatible).
        os.makedirs(part_dir, exist_ok=True)
        body_paths: List[str] = []
        marker_entries: List[AudioEntry] = []
        body_pieces = pieces  # (chunk_text, voice_override)
        total_count = len(body_pieces) + (1 if title_text is not None else 0)

        if title_text is not None and migrate_titles:
            # first run with the title layout: the old first body part has
            # title audio baked in, which duration checks cannot tell apart —
            # drop it once so it regenerates title-free (later runs have a
            # manifest and skip this; missing files are simply re-queued)
            first_body = os.path.join(part_dir, f"{chapter_number:03d}_{safe_title}_part001.mp3")
            try:
                if os.path.isfile(first_body):
                    os.remove(first_body)
                    print(f"{label}: title split off for the pause — regenerating first part")
            except OSError:
                pass

        title_path: Optional[str] = None
        title_ok = True
        if title_text is not None:
            title_path = os.path.join(output_dir, f"{chapter_number:03d}_{safe_title}.title.mp3")
            marker_entries.append((chapter_number, title, title_path))
            title_ok = _ensure_valid_or_drop(title_path, title_text, f"{label} title", rate=rate)
            if not title_ok:
                jobs.append(
                    PartJob(
                        chapter_number=chapter_number,
                        chapter_title=title,
                        part_number=0,
                        part_count=total_count,
                        text=title_text,
                        output_path=title_path,
                        is_final_chapter_file=False,
                        voice=None,
                        append_silence_sec=TITLE_PAUSE_SEC,
                    )
                )

        # A merged chapter file with gaps (built from truncated parts by an
        # older run) must not shadow its parts: verify against the body text.
        # The merge is also stale whenever the title part is (re)generated:
        # it was built without the title+pause.
        merged_ok = _ensure_valid_or_drop(chapter_mp3, body_text, label, rate=rate) and title_ok
        if title_path is not None and not merged_ok:
            # drop a stale merge so finalize rebuilds it (cheap concat; parts
            # are reused) — a valid chapter without the title+pause must not
            # shadow the freshly generated title part
            try:
                if os.path.isfile(chapter_mp3):
                    os.remove(chapter_mp3)
            except OSError:
                pass

        for part_number, (chunk_text, chunk_voice) in enumerate(body_pieces, 1):
            part_path = os.path.join(part_dir, f"{chapter_number:03d}_{safe_title}_part{part_number:03d}.mp3")
            body_paths.append(part_path)
            marker_entries.append((chapter_number, f"{title} - part {part_number}", part_path))

            if not merged_ok and not _ensure_valid_or_drop(
                part_path, chunk_text, f"{label} part {part_number:03d}", rate=rate
            ):
                jobs.append(
                    PartJob(
                        chapter_number=chapter_number,
                        chapter_title=title,
                        part_number=part_number,
                        part_count=total_count,
                        text=chunk_text,
                        output_path=part_path,
                        is_final_chapter_file=False,
                        voice=chunk_voice,
                    )
                )

        plans.append(ChapterPlan(chapter_number, title, chapter_mp3, body_paths, marker_entries, title_path))

    return plans, jobs


async def tts_text_to_mp3(
    text: str,
    output_path: str,
    voice: str,
    retries: int = 5,
    rate: Optional[str] = None,
    on_retry: Optional[Callable[[int, Exception], None]] = None,
    _demote_truncated: bool = True,
) -> None:
    """
    Core-owned Edge TTS execution (ratyfikacja speak.py:116).

    - edge_tts lazy import inside loop (CI without deps still imports core.tts)
    - for attempt in 1..retries: edge_tts.Communicate(text,voice[,rate]).save
    - rate like '+25%' (normalized upstream); omitted → Edge default '+0%'
    - on_retry(attempt, error) fires before every backoff sleep so the
      adaptive pool can treat retries as a throttling signal
    - after each save verify_part_audio: invalid file is deleted and the
      attempt counts as failed (empty/partial writes are retried; a
      "truncated" verdict triggers the built-in troubleshooter —
      _autosplit_truncated regenerates the part in halves — and, at normal
      rates, is then retried like any transient failure since Edge cuts
      overlong requests deterministically but also flakes occasionally;
      the retry demotion applies to the top-level call only — nested
      recovery fails fast to bound total work; extreme rates fail fast,
      and exhausted retries surface the actionable truncation error)
    - `_demote_truncated=False` (used by the troubleshooter itself for
      sub-parts) disables the retry demotion: nested calls raise the
      truncation error immediately instead of multiplying attempts
    - wait = min(20, 2*attempt) + asyncio.sleep + log retry {attempt}/{retries-1} for {name}
    - raise RuntimeError after exhausting retries with last_error chained

    Pure Core — no adapters/*, no epub/filters (ffmpeg only for the
    truncation auto-split concat).
    """
    last_error: Optional[Exception] = None
    truncated_error: Optional[_TruncatedPartError] = None
    last_failure_truncated = False
    split_attempted = False

    for attempt in range(1, retries + 1):
        last_failure_truncated = False
        try:
            import edge_tts  # lazy — keep core importable without edge-tts

            kwargs: dict = {}
            if rate:
                kwargs["rate"] = rate
            communicate = edge_tts.Communicate(text, voice, **kwargs)
            await communicate.save(output_path)
            ok, reason = verify_part_audio(output_path, text, rate=rate)
            if ok:
                return
            # saved file failed verification — remove so resume never reuses it
            try:
                Path(output_path).unlink(missing_ok=True)
            except Exception:
                pass
            if reason == "truncated":
                last_failure_truncated = True
                if truncated_error is None:
                    truncated_error = _TruncatedPartError(
                        f"TTS output truncated for {Path(output_path).name} "
                        f"({len(text)} chars) even after automatic splitting — "
                        f"try a lower --rate, a different voice, or --chunk-size 2000 and re-run"
                    )
                # built-in troubleshooter: Edge cuts overlong requests
                # deterministically, so instead of aborting the whole build,
                # split the part and regenerate it in halves (recursively).
                if not split_attempted:
                    split_attempted = True
                    if await _autosplit_truncated(
                        text, output_path, voice, retries, rate, on_retry
                    ):
                        return
                if _rate_is_normal(rate) and _demote_truncated:
                    # at normal rates a truncated verdict is suspect (likely a
                    # transient Edge cut): retry like any invalid file instead
                    # of aborting the build
                    raise RuntimeError(
                        f"TTS saved truncated audio for {Path(output_path).name} — retrying"
                    )
                raise truncated_error
            # non-truncated but invalid (empty/partial/unprobed): reuse the
            # generic retry path below so it gets backoff logging + sleep
            raise RuntimeError(
                f"TTS saved invalid audio ({reason}) for {Path(output_path).name}"
            )
        except (ModuleNotFoundError, ImportError) as e:
            raise RuntimeError(f"edge-tts not installed for {output_path}: {e}") from e
        except _TruncatedPartError:
            raise
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
                if on_retry is not None:
                    try:
                        on_retry(attempt, e)
                    except Exception:
                        pass
                await asyncio.sleep(wait_seconds)

    # retries exhausted: prefer the actionable truncation error when the last
    # attempt failed truncated (auto-split + plain retries all tried)
    if last_failure_truncated and truncated_error is not None:
        raise truncated_error from last_error
    raise RuntimeError(f"TTS failed after {retries} attempts for {output_path}: {last_error}") from last_error


#: Auto-split floor for the truncation troubleshooter: parts at or below
#: this size are synthesized as-is; persistent truncation below it raises
#: instead of recursing forever.
TRUNC_SPLIT_FLOOR = 500


def _rate_is_normal(rate: Optional[str]) -> bool:
    """True when |rate| is within the UI slider range (±50%).

    At normal rates short audio is suspect — most likely a transient Edge
    cut — so the troubleshooter retries instead of aborting. At extreme
    rates the duration floor is already scaled, and a truncated verdict is
    trustworthy enough to fail fast.
    """
    try:
        num = int(normalize_tts_rate(rate).rstrip("%"))
    except Exception:
        return True
    return abs(num) <= 50


async def _autosplit_truncated(
    text: str,
    output_path: str,
    voice: str,
    retries: int,
    rate: Optional[str],
    on_retry: Optional[Callable[[int, Exception], None]],
) -> bool:
    """Regenerate a truncated part in halves; True when healed.

    Splits `text`, synthesizes each half via tts_text_to_mp3 (which recurses
    here if a half truncates too), concatenates the halves over `output_path`,
    and re-verifies. Returns False when splitting cannot help: text already
    at/below the floor, unsplittable, ffmpeg unavailable for the concat, or
    the re-assembled output still does not verify.
    """
    name = Path(output_path).name
    if len(text) <= TRUNC_SPLIT_FLOOR:
        return False
    if not ffmpeg_available():
        return False
    sub_texts = split_text_for_tts(text, max_chars=max(TRUNC_SPLIT_FLOOR, len(text) // 2))
    if len(sub_texts) < 2:
        return False
    print(
        f"        truncated {name} ({len(text)} chars) — "
        f"auto-splitting into {len(sub_texts)} parts and regenerating"
    )
    tmp_paths = [f"{output_path}.autosplit{i}.mp3" for i in range(len(sub_texts))]
    try:
        for sub_text, tmp in zip(sub_texts, tmp_paths):
            # nested recovery fails fast (no demotion retries): the top-level
            # call already provides the retry breadth for transient cuts
            await tts_text_to_mp3(
                sub_text, tmp, voice, retries=retries, rate=rate,
                on_retry=on_retry, _demote_truncated=False,
            )
        concat_mp3_files(tmp_paths, output_path)
    except Exception as e:
        print(f"        auto-split regenerate failed for {name}: {e}")
        try:
            Path(output_path).unlink(missing_ok=True)
        except Exception:
            pass
        return False
    finally:
        for tmp in tmp_paths:
            try:
                Path(tmp).unlink(missing_ok=True)
            except Exception:
                pass
    ok, reason = verify_part_audio(output_path, text, rate=rate)
    if ok:
        print(f"        auto-split healed {name}")
        return True
    print(f"        auto-split output still invalid ({reason}) for {name}")
    try:
        Path(output_path).unlink(missing_ok=True)
    except Exception:
        pass
    return False


#: Adaptive pool: +1 worker after this many consecutive clean parts.
ADAPTIVE_GROW_AFTER = 8

#: Adaptive pool hard ceiling (> configured parallel, which is clamped 1–6).
ADAPTIVE_MAX_PARALLEL = 12


class AdaptiveGate:
    """Dynamic concurrency limiter (AIMD) for TTS part workers.

    Starts at the configured parallel, grows +1 after ADAPTIVE_GROW_AFTER
    consecutive clean parts (no retry), and halves on any retry — Edge
    throttling surfaces as retries followed by backoff, so the pool
    self-tunes without probing beyond what the service tolerates.
    Floor 1, ceiling `maximum`.

    `release()` is synchronous on purpose: workers call it from a `finally`
    that may run while the task is being cancelled, where awaiting would
    risk re-entrant cancellation.
    """

    def __init__(self, initial: int, maximum: int):
        self.maximum = max(1, int(maximum))
        self.limit = max(1, min(int(initial), self.maximum))
        self.active = 0
        self._streak = 0
        self._waiters: List[asyncio.Future] = []

    def _wake(self) -> None:
        while self._waiters and self.active < self.limit:
            fut = self._waiters.pop(0)
            if not fut.done():
                fut.set_result(True)
                return

    def _set_limit(self, new: int) -> None:
        new = max(1, min(int(new), self.maximum))
        if new != self.limit:
            self.limit = new
            if self.active < self.limit:
                self._wake()

    def note_clean_success(self) -> None:
        """One part finished with zero retries — grow after a streak."""
        if self.limit >= self.maximum:
            self._streak = 0
            return
        self._streak += 1
        if self._streak >= ADAPTIVE_GROW_AFTER:
            self._streak = 0
            self._set_limit(self.limit + 1)

    def note_retry(self) -> None:
        """A part needed a retry — treat as throttling and back off."""
        self._streak = 0
        self._set_limit(self.limit // 2)

    async def acquire(self) -> None:
        while True:
            if self.active < self.limit:
                self.active += 1
                return
            fut = asyncio.get_running_loop().create_future()
            self._waiters.append(fut)
            try:
                await fut
            finally:
                try:
                    self._waiters.remove(fut)
                except ValueError:
                    pass

    def release(self) -> None:
        if self.active > 0:
            self.active -= 1
        self._wake()


async def run_part_jobs(
    jobs: List[PartJob],
    voice: str,
    parallel: int,
    retries: int,
    on_part_status=None,
    on_log=None,
    on_progress=None,
    rate: Optional[str] = None,
    adaptive: bool = False,
    parallel_max: Optional[int] = None,
    engine: str = "edge",
    local_voice: Optional[str] = None,
) -> None:
    """
    Global parallel PartJob queue — deterministyczny reading-order.

    - asyncio.Queue[Optional[PartJob]] filled for job in jobs: put_nowait(job) then sentinel None×pool
    - workers pool = asyncio.create_task(worker(i+1))
    - worker while True: job=await queue.get(); if job is None: task_done/break
    - rate like '+25%' forwarded to tts_text_to_mp3 (omit = Edge default)
    - engine 'auto'|'edge'|'local': 'auto' uses local Piper when the machine is
      fast enough (>= LOCAL_MIN_CORES) and the model is downloaded, else Edge;
      'local' runs fully offline (pool = cpu cores capped at 8, no adaptive gate)
    - adaptive=True: concurrency starts at `parallel` (clamp 1–6) and self-tunes
      via AdaptiveGate up to ADAPTIVE_MAX_PARALLEL (override: parallel_max) —
      +1 after ADAPTIVE_GROW_AFTER clean parts, halved on any retry
    - skip if output verifies (verify_part_audio): log skip + size_kb, no TTS call
    - else if file exists but invalid (too_small/truncated/no_duration): delete + regenerate
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

    # Engine resolution: 'auto' falls back to Edge when the local model is
    # missing or the machine is below the local-synthesis CPU threshold.
    engine_used = "edge"
    local_voice_eff: Optional[str] = None
    if isinstance(engine, str) and engine.strip().lower() not in ("", "edge"):
        from core.tts_local import DEFAULT_LOCAL_VOICE, effective_local_parallel, resolve_engine

        try:
            engine_used = resolve_engine(engine, local_voice)
        except ValueError as e:
            print(str(e))
            if on_log:
                try:
                    on_log(str(e))
                except Exception:
                    pass
            raise
        if engine_used == "local":
            local_voice_eff = (
                local_voice if isinstance(local_voice, str) and local_voice.strip() else DEFAULT_LOCAL_VOICE
            )
            if isinstance(engine, str) and engine.strip().lower() == "local":
                _engine_msg = f"engine: local Piper {local_voice_eff} (offline synthesis)"
            else:
                _engine_msg = f"engine: auto -> local Piper {local_voice_eff} (fast CPU, offline synthesis)"
        else:
            _engine_msg = "engine: auto -> Edge TTS (local model not downloaded or CPU below threshold)"
        print(_engine_msg)
        if on_log:
            try:
                on_log(_engine_msg)
            except Exception:
                pass

    _resume_lock: Any = None
    try:
        _resume_lock = acquire_resume_lock(_resume_root_for_jobs(jobs))
    except RuntimeError as e:
        print(str(e))
        if on_log:
            try:
                on_log(str(e))
            except Exception:
                pass
        raise

    # R3: refresh lock mtime while the run is alive — without a heartbeat a
    # conversion longer than RESUME_LOCK_STALE_SEC (600s) would look abandoned
    # and a second process would reclaim (and later delete) the lock.
    _lock_hb: Any = None
    if _resume_lock is not None:
        async def _lock_heartbeat(lock_path: Any) -> None:
            while True:
                await asyncio.sleep(60)
                try:
                    os.utime(lock_path, None)
                except Exception:
                    pass

        try:
            _lock_hb = asyncio.create_task(_lock_heartbeat(_resume_lock))
        except Exception:
            _lock_hb = None

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

    # Worker pool size = concurrency ceiling; the AdaptiveGate throttles
    # actual concurrency (and can raise it up to parallel_max while running).
    # Local (Piper) runs are CPU-bound: pool = cpu cores (capped), no gate.
    gate: Optional[AdaptiveGate] = None
    pool_size = parallel
    if engine_used == "local":
        pool_size = effective_local_parallel()
    elif adaptive:
        max_par = ADAPTIVE_MAX_PARALLEL
        try:
            if parallel_max is not None:
                max_par = max(parallel, min(int(parallel_max), 64))
        except Exception:
            max_par = ADAPTIVE_MAX_PARALLEL
        max_par = max(parallel, max_par)
        gate = AdaptiveGate(parallel, max_par)
        pool_size = max(parallel, min(max_par, len(jobs)))

    for _ in range(pool_size):
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

            acquired = False
            try:
                if gate is not None:
                    await gate.acquire()
                    acquired = True
                # Resume gate: an existing file is reused only if it verifies.
                # Stale truncated/partial files from earlier runs are deleted
                # and regenerated — previously they were skipped forever,
                # leaving silent gaps in the finished audiobook.
                needs_gen = True
                ok, reason = verify_part_audio(job.output_path, job.text, rate=rate)
                if ok:
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
                    needs_gen = False
                elif reason != "missing":
                    try:
                        Path(job.output_path).unlink(missing_ok=True)
                    except Exception:
                        pass
                    msg_invalid = (
                        f"worker {worker_id}: invalid Chapter {job.chapter_number:03d} "
                        f"part {job.part_number:03d}/{job.part_count:03d} ({reason}), regenerating"
                    )
                    print(msg_invalid)
                    _emit_log(msg_invalid)
                if needs_gen:
                    msg_start = (
                        f"worker {worker_id}: start Chapter {job.chapter_number:03d} "
                        f"part {job.part_number:03d}/{job.part_count:03d}"
                    )
                    print(msg_start)
                    _emit_log(msg_start)
                    _emit_log(f"start Chapter {job.chapter_number:03d} part {job.part_number:03d}/{job.part_count:03d}")
                    _emit_part(job, "fetching")
                    part_retried = False

                    def _on_retry(_attempt, _err) -> None:
                        nonlocal part_retried
                        part_retried = True
                        if gate is not None:
                            before = gate.limit
                            gate.note_retry()
                            if gate.limit != before:
                                _emit_log(
                                    f"parallel: throttling detected, reducing TTS concurrency {before} -> {gate.limit}"
                                )

                    tts_kwargs: dict = {"retries": retries}
                    if rate:
                        tts_kwargs["rate"] = rate
                    try:
                        if engine_used == "local":
                            from core.tts_local import tts_text_to_mp3_local

                            await asyncio.to_thread(
                                tts_text_to_mp3_local, job.text, job.output_path, local_voice_eff, **tts_kwargs
                            )
                        else:
                            if gate is not None:
                                tts_kwargs["on_retry"] = _on_retry
                            # dialogue voice override (Edge engine only; the
                            # local engine ignores per-part voices)
                            eff_voice = job.voice or voice
                            await tts_text_to_mp3(job.text, job.output_path, eff_voice, **tts_kwargs)
                    except asyncio.CancelledError:
                        # cancelled mid-save: drop truncated file so resume heals (H6)
                        try:
                            Path(job.output_path).unlink(missing_ok=True)
                        except Exception:
                            pass
                        _emit_part(job, "error")
                        raise
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
                    # title pause: append silence to the finished part so the
                    # chapter merge plays "title … pause … text". A failed
                    # append only drops the pause (loud warning), never the part.
                    try:
                        silence_sec = float(job.append_silence_sec or 0.0)
                    except Exception:
                        silence_sec = 0.0
                    if silence_sec > 0:
                        pause_path = ensure_pause_file(
                            os.path.dirname(job.output_path) or ".", silence_sec
                        )
                        if pause_path is None:
                            _emit_log(
                                f"warning: no pause appended to Chapter {job.chapter_number:03d} title "
                                f"(ffmpeg unavailable)"
                            )
                        else:
                            try:
                                _append_silence(job.output_path, pause_path)
                            except Exception as e:
                                _emit_log(
                                    f"warning: title pause skipped for Chapter {job.chapter_number:03d}: {e}"
                                )
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
                    if gate is not None and not part_retried:
                        before = gate.limit
                        gate.note_clean_success()
                        if gate.limit != before:
                            _emit_log(
                                f"parallel: stable, increasing TTS concurrency {before} -> {gate.limit}"
                            )

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
                if acquired and gate is not None:
                    gate.release()
                queue.task_done()

    workers = [asyncio.create_task(worker(i + 1)) for i in range(pool_size)]

    try:
        await asyncio.gather(*workers)
        # ensure queue drained (workers already called task_done for each item)
        try:
            await asyncio.wait_for(queue.join(), timeout=0.1)
        except asyncio.TimeoutError:
            pass
    except asyncio.CancelledError:
        for task in workers:
            task.cancel()
        # drop any partial file from the cancelled job is handled per-worker;
        # here just drain + propagate so resume never reuses truncated output
        while True:
            try:
                queue.get_nowait()
                queue.task_done()
            except asyncio.QueueEmpty:
                break
            except Exception:
                break
        raise
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
    finally:
        if _lock_hb is not None:
            try:
                _lock_hb.cancel()
            except Exception:
                pass
        release_resume_lock(_resume_lock)


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def subprocess_kwargs() -> dict:
    """Extra subprocess kwargs shared by all ffmpeg/ffprobe calls.

    On Windows, CREATE_NO_WINDOW so the GUI never flashes a console window
    when merging chapters or probing durations (Rust side already spawns
    the sidecar itself with CREATE_NO_WINDOW).
    """
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}
    return {}


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
    # Atomic publish: ffmpeg writes a sidecar .tmp and we os.replace it into
    # place on success. A hard kill (GUI Stop / crash) mid-encode then leaves
    # at worst a stray .tmp, never a truncated chapter MP3 that resume would
    # mistake for a finished merge (size+duration gates can pass on partials).
    tmp_output = output_path + ".tmp"
    try:
        with open(concat_file, "w", encoding="utf-8") as f:
            for p in input_paths:
                if not os.path.isfile(p):
                    raise FileNotFoundError(f"missing concat input: {p}")
                safe = os.path.abspath(p).replace("\\", "/").replace("'", "'\\''")
                f.write(f"file '{safe}'\n")

        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_file, "-c", "copy", "-f", "mp3", tmp_output],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **subprocess_kwargs(),
        )
        os.replace(tmp_output, output_path)
    finally:
        try:
            if os.path.exists(concat_file):
                os.remove(concat_file)
        except OSError:
            pass
        try:
            if os.path.exists(tmp_output):
                os.remove(tmp_output)
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
            **subprocess_kwargs(),
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


def finalize_chapter_audio(
    plans: List[ChapterPlan],
    keep_parts: bool,
    on_chapter: Optional[Callable[[int, int], None]] = None,
    normalize_audio: bool = False,
    trim_silence: bool = False,
) -> List[AudioEntry]:
    """Merge part files into per-chapter MP3s (or keep parts without ffmpeg).

    `on_chapter(done, total)` fires once per plan (all exit paths) so long
    batch jobs can show merge progress. Optional — CLI/tests omit it.

    With `normalize_audio`/`trim_silence`, each finished chapter file is
    re-encoded through loudnorm and/or leading/trailing silence trimming
    (postprocess_chapter_file) before it is listed.
    """
    audio_entries: List[AudioEntry] = []
    has_ffmpeg = ffmpeg_available()

    print("\nFinalizing chapter files...")

    _total_plans = len(plans)
    _done_plans = 0

    def _emit_chapter() -> None:
        nonlocal _done_plans
        _done_plans += 1
        if on_chapter is not None:
            try:
                on_chapter(_done_plans, _total_plans)
            except Exception:
                pass

    for plan in plans:
        if not plan.part_paths:
            _emit_chapter()
            continue

        # merge inputs: title part (with its appended pause) ahead of bodies
        title_part = getattr(plan, "title_part_path", None)
        merge_inputs = ([title_part] if title_part else []) + list(plan.part_paths)

        # Single-chunk chapter.
        if len(plan.part_paths) == 1 and plan.part_paths[0] == plan.chapter_mp3:
            # validate exists and non-empty / is file
            try:
                if os.path.isfile(plan.chapter_mp3) and os.path.getsize(plan.chapter_mp3) > 0:
                    if normalize_audio or trim_silence:
                        postprocess_chapter_file(plan.chapter_mp3, normalize_audio, trim_silence)
                    audio_entries.append((plan.chapter_number, plan.title, plan.chapter_mp3))
                else:
                    # zero-byte or not a file -> treat as missing
                    if os.path.exists(plan.chapter_mp3):
                        print(f"Warning: chapter MP3 exists but empty/corrupt: {plan.chapter_mp3}")
                    print(f"Warning: missing chapter MP3: {plan.chapter_mp3}")
            except OSError:
                print(f"Warning: missing chapter MP3: {plan.chapter_mp3}")
            _emit_chapter()
            continue

        # Multi-part chapter.
        if os.path.isfile(plan.chapter_mp3):
            try:
                size = os.path.getsize(plan.chapter_mp3)
                if size == 0:
                    print(f"Warning: existing merged file empty, will re-merge: {plan.chapter_mp3}")
                else:
                    # Corrupt zero-duration merges must not be reused when
                    # ffprobe can tell (size gate alone keeps gappy merges).
                    # Only applies to plausibly-large files — tiny test
                    # fixtures stay on the legacy size path.
                    try:
                        if (
                            size >= MIN_PART_BYTES
                            and ffprobe_available()
                            and get_duration_ms(plan.chapter_mp3) <= 0
                        ):
                            print(f"Warning: existing merged file has no duration, will re-merge: {plan.chapter_mp3}")
                        else:
                            audio_entries.append((plan.chapter_number, plan.title, plan.chapter_mp3))
                            size_kb = size // 1024
                            print(f"Chapter {plan.chapter_number:03d}: existing merged file reused ({size_kb} KB)")
                            _emit_chapter()
                            continue
                    except Exception:
                        audio_entries.append((plan.chapter_number, plan.title, plan.chapter_mp3))
                        size_kb = size // 1024
                        print(f"Chapter {plan.chapter_number:03d}: existing merged file reused ({size_kb} KB)")
                        _emit_chapter()
                        continue
            except OSError:
                pass

        missing_parts = [p for p in merge_inputs if not os.path.exists(p)]
        if missing_parts:
            print(f"Warning: Chapter {plan.chapter_number:03d} has missing part files; keeping available parts only.")
            for entry in (plan.marker_entries_if_unmerged or []):
                try:
                    if os.path.exists(entry[2]):
                        audio_entries.append(entry)
                except Exception:
                    continue
            _emit_chapter()
            continue

        if has_ffmpeg:
            print(f"Chapter {plan.chapter_number:03d}: merging {len(merge_inputs)} part(s)")
            try:
                concat_mp3_files(merge_inputs, plan.chapter_mp3)
                if normalize_audio or trim_silence:
                    postprocess_chapter_file(plan.chapter_mp3, normalize_audio, trim_silence)
                audio_entries.append((plan.chapter_number, plan.title, plan.chapter_mp3))
                if not keep_parts:
                    for part_path in plan.part_paths:
                        try:
                            if os.path.exists(part_path):
                                os.remove(part_path)
                        except OSError:
                            continue
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
                # NOTE: do NOT delete part files on merge failure — fallback
                # entries reference them (H1 fix).
        else:
            print(f"Chapter {plan.chapter_number:03d}: ffmpeg unavailable, keeping {len(plan.part_paths)} part files")
            for entry in (plan.marker_entries_if_unmerged or []):
                try:
                    if os.path.exists(entry[2]):
                        audio_entries.append(entry)
                except Exception:
                    continue
            # fallback: if marker entries contain missing paths, already filtered; extend only existing
        _emit_chapter()
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


def _parse_audio_bitrate(value: Any, default: str = "32k") -> str:
    """Normalize an M4B/M4A audio bitrate like '32k' (16k-128k).

    Spoken-word TTS sources are ~24-48k MP3, so re-encoding above 64k only
    grows the file. Raises ValueError on garbage.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        value = default
    text = str(value).strip().lower()
    match = re.fullmatch(r"(\d+)\s*k", text)
    if not match:
        raise ValueError(f"bitrate must be like 32k (16k-128k), got {value!r}")
    kbps = int(match.group(1))
    if kbps < 16 or kbps > 128:
        raise ValueError(f"bitrate must be like 32k (16k-128k), got {value!r}")
    return f"{kbps}k"


def _estimate_m4b_size(bitrate: str, total_ms: int) -> int:
    """Expected M4B bytes for CBR encode + container slack (progress denominator)."""
    try:
        kbps = int(bitrate[:-1])
    except Exception:
        kbps = 32
    return max(1, int(kbps * 1000 / 8 * (total_ms / 1000) * 1.1) + 65536)


def build_m4b(
    output_dir: str,
    audio_entries: List[AudioEntry],
    book_title: str,
    ext: str = "m4b",
    bitrate: str = "32k",
    on_progress: Optional[Callable[[int, int], None]] = None,
    on_probe: Optional[Callable[[int, int], None]] = None,
    cover_path: Optional[str] = None,
    artist: Optional[str] = None,
) -> None:
    # defensive ext whitelist
    if ext not in ("m4b", "m4a"):
        ext = "m4b"
    try:
        bitrate = _parse_audio_bitrate(bitrate)
    except ValueError as e:
        raise ValueError(str(e)) from e
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
            f.write(f"title={escape_ffmeta(book_title)}\n")
            if isinstance(artist, str) and artist.strip():
                f.write(f"artist={escape_ffmeta(artist.strip()[:200])}\n")
            f.write("\n")
            cursor = 0
            _probe_total = len(audio_entries)
            for _probe_i, (chapter_number, marker_title, path) in enumerate(audio_entries, 1):
                try:
                    duration = get_duration_ms(path)
                except Exception:
                    duration = 0
                if on_probe is not None:
                    try:
                        on_probe(_probe_i, _probe_total)
                    except Exception:
                        pass
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

        # Size-poll progress for the (potentially multi-minute) encode so GUIs
        # can show a live ETA. Daemon thread, stopped in finally below.
        _expected_total = _estimate_m4b_size(bitrate, cursor)
        _prog_stop = threading.Event()

        def _poll_output_size() -> None:
            while not _prog_stop.wait(2.0):
                try:
                    _sz = os.path.getsize(out_path) if os.path.exists(out_path) else 0
                except OSError:
                    _sz = 0
                if on_progress is not None and _expected_total > 0:
                    try:
                        on_progress(min(_sz, _expected_total), _expected_total)
                    except Exception:
                        pass

        _prog_thread = threading.Thread(target=_poll_output_size, daemon=True)
        _prog_thread.start()

        cover_ok: Optional[str] = None
        if isinstance(cover_path, str) and cover_path.strip():
            _cp = cover_path.strip()
            if os.path.isfile(_cp) and os.path.splitext(_cp)[1].lower() in (".jpg", ".jpeg", ".png"):
                cover_ok = _cp
            else:
                print(f"Warning: cover art not usable (need .jpg/.png), continuing without it: {cover_path}")

        def _encode_args(with_cover: Optional[str]) -> list:
            args = [
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
            ]
            if with_cover:
                args += ["-i", with_cover]
            args += ["-map_metadata", "1", "-map", "0:a"]
            if with_cover:
                args += ["-map", "2:v", "-c:v", "copy", "-disposition:v", "attached_pic"]
            args += ["-c:a", "aac", "-b:a", bitrate, out_path]
            return args

        try:
            subprocess.run(
                _encode_args(cover_ok),
                check=True,
                **subprocess_kwargs(),
            )
        except Exception as e:
            if cover_ok is None:
                raise
            # cover-related encode failure must not lose the audiobook:
            # retry the exact same encode without cover art
            print(f"Warning: {ext.upper()} encode with cover failed ({e}) — retrying without cover art.")
            subprocess.run(
                _encode_args(None),
                check=True,
                **subprocess_kwargs(),
            )
    finally:
        try:
            _prog_stop.set()
        except Exception:
            pass
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
    "user_output_base",
    "resolve_output_dir",
    "PartJob",
    "ChapterPlan",
    "MIN_PART_BYTES",
    "EXPECTED_TTS_CPS",
    "MIN_DURATION_RATIO",
    "MIN_TEXT_LEN_FOR_DURATION_CHECK",
    "TRUNC_SPLIT_FLOOR",
    "TITLE_PAUSE_SEC",
    "verify_part_audio",
    "split_text_for_tts",
    "split_dialogue",
    "split_title_body",
    "ensure_pause_file",
    "check_build_identity",
    "postprocess_chapter_file",
    "verify_part_audio",
    "split_text_for_tts",
    "build_generation_plan",
    "tts_text_to_mp3",
    "run_part_jobs",
    "ffmpeg_available",
    "ffprobe_available",
    "subprocess_kwargs",
    "concat_mp3_files",
    "get_duration_ms",
    "escape_ffmeta",
    "finalize_chapter_audio",
    "build_m4b",
]
