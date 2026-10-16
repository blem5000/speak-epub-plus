"""
core/audio.py — Audiobook assembly gate (Step 7: MP3/M4B/M4A in the GUI).

Mirrors core/epub.py's offline gate for audio: cached chapter HTML
-> clean -> filter (text) -> sentence chunking -> Edge TTS PartJob queue
-> per-chapter MP3 merge -> optional single M4B/M4A with chapter markers.

AD-8: EPUB and audio are sibling artifacts from the same cache; TTS reads
only cached HTML (CACHE_MISS otherwise — fetch chapters first).
Pure Core module: static imports are stdlib-only or installed deps
(ebooklib/bs4 live inside functions, same as epub.py).
"""
from __future__ import annotations

import contextlib
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.epub import sanitize_filename
from core.fetch import get_cache_path, read_cache
from core.filters import apply_filters, sanitize_filters
from core.tts import (
    build_generation_plan,
    build_m4b,
    ffmpeg_available,
    finalize_chapter_audio,
    resolve_output_dir,
    run_part_jobs,
    split_text_for_tts,
)

ChapterText = Tuple[int, str, str]  # (chapter_number, title, text)

MAX_AUDIO_RANGE = 500
_HEARTBEAT_SEC = 20  # tests patch this down to ~0.2


@contextlib.contextmanager
def _heartbeat_scope(emit: Callable[[str], None], interval: float | None = None):
    """Emit 'still working…' lines while long silent work runs.

    The desktop sidecar treats minutes of stdout silence as a hung backend
    (notably the final M4B re-encode of a big book). A daemon thread beats
    every `interval` seconds until the scope exits. Harmless everywhere else
    (CLI prints one extra line per interval).
    """
    import threading
    import time

    if interval is None:
        interval = _HEARTBEAT_SEC
    stop = threading.Event()
    start = time.monotonic()

    def _beat() -> None:
        while not stop.wait(interval):
            try:
                emit(f"still working... {int(time.monotonic() - start)}s elapsed")
            except Exception:
                pass

    th = threading.Thread(target=_beat, daemon=True)
    th.start()
    try:
        yield
    finally:
        stop.set()


def _to_int(v: Any, default: Optional[int] = None) -> Optional[int]:
    if v is None or v == "":
        return default
    try:
        iv = int(v)  # type: ignore[arg-type]
    except Exception:
        return default
    if iv < 1:
        return 1
    return max(1, min(iv, 100000))


def _load_filters(filters: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    if filters is not None:
        try:
            return sanitize_filters(filters)
        except Exception:
            return []
    try:
        from core.config import load_store  # dynamic to avoid import cycles

        store = load_store()
        return sanitize_filters(store.get("filters", []))
    except Exception:
        return []


def _resolve_audio_urls(
    novel_url: str,
    from_i: int,
    to_i: int,
    chapter_urls: Optional[List[Any]],
    cache_dir: Path | str | None,
) -> List[str]:
    """Offline URL resolution: explicit urls win, else _CHAPTER_CACHE lookup.

    Raises AdapterError CACHE_MISS with .missing when chapters are not fetched.
    """
    from core.ports import AdapterError

    if chapter_urls is not None and isinstance(chapter_urls, (list, tuple)) and len(chapter_urls) > 0:
        cleaned: List[str] = []
        for u in chapter_urls:
            if isinstance(u, str) and u.strip():
                cleaned.append(u.strip())
            elif isinstance(u, dict):
                uu = u.get("url") or u.get("link") or u.get("href")
                if isinstance(uu, str) and uu.strip():
                    cleaned.append(uu.strip())
        desired = list(dict.fromkeys(cleaned))
        if not desired:
            raise ValueError("urls empty after trim/dedup")
    else:
        # derive from the in-memory chapter list cache (populated by listChapters)
        try:
            from core.config import _CHAPTER_CACHE, _normalize_cache_key  # dynamic, no cycles

            key = _normalize_cache_key(novel_url)
            cached_list = _CHAPTER_CACHE.get(key, [])
            idx_to_url: Dict[int, str] = {}
            for item in cached_list:
                try:
                    if isinstance(item, dict):
                        idx, url = item.get("index"), item.get("url") or item.get("link")
                    else:
                        idx, url = getattr(item, "index", None), getattr(item, "url", None)
                    if idx is not None and url:
                        idx_to_url[int(idx)] = str(url).strip()
                except Exception:
                    continue
            desired = []
            for idx in range(from_i, to_i + 1):
                if idx in idx_to_url:
                    desired.append(idx_to_url[idx])
                else:
                    desired.append(f"{novel_url.rstrip('/')}/chapter/{idx}")
        except Exception:
            desired = [f"{novel_url.rstrip('/')}/chapter/{idx}" for idx in range(from_i, to_i + 1)]

    missing = [u for u in desired if read_cache(u, cache_dir) is None]
    if missing:
        err = AdapterError(f"CACHE_MISS: missing {len(missing)} chapters", code="CACHE_MISS")
        try:
            err.missing = missing  # type: ignore[attr-defined]
        except Exception:
            pass
        raise err
    return desired


def _chapter_texts(
    desired_urls: List[str],
    from_i: int,
    cache_dir: Path | str | None,
    filters: List[Dict[str, Any]],
    start_selector: Optional[str],
    end_selector: Optional[str],
    logs: List[str],
    novel_url: str = "",
) -> List[ChapterText]:
    """Read cache -> clean -> block lines -> filter (text) per chapter.

    Returns (number, title, text) with text as "\\n"-joined block lines
    (clean_html joins everything with spaces, so block structure is rebuilt
    via html_to_block_lines — also what boilerplate detection needs).
    """
    from bs4 import BeautifulSoup

    from core.clean import clean_html, resolve_selectors
    from core.filters import html_to_block_lines

    # Effective selectors: explicit params win, else the adapter default plus
    # any saved user override (dynamic import — same AD-1 exception as
    # core.config / adapters, keeps static importlinter contract green).
    try:
        import importlib as _il_sel

        _mod_sel = _il_sel.import_module("adapters.novelphoenix")
        _NPAdapter = getattr(_mod_sel, "NovelPhoenixAdapter")
        selectors = resolve_selectors(_NPAdapter())
        eff_start = start_selector if start_selector is not None else selectors.start
        eff_end = end_selector if end_selector is not None else selectors.end
    except Exception:
        eff_start, eff_end = "div#chapter-content", None
    if isinstance(eff_start, str):
        eff_start = eff_start.strip() or "div#chapter-content"
    else:
        eff_start = "div#chapter-content"
    if isinstance(eff_end, str):
        eff_end = eff_end.strip() or None

    out: List[ChapterText] = []
    try:
        from core.epub import _list_title_map as _audio_tlm_fn  # type: ignore[attr-defined]

        _audio_tlm = _audio_tlm_fn(novel_url)
    except Exception:
        _audio_tlm = {}
    for pos, url in enumerate(desired_urls):
        ch_num = from_i + pos
        raw_html = read_cache(url, cache_dir)
        if raw_html is None:  # guarded earlier; fail fast anyway
            raise FileNotFoundError(f"cache miss chapter {ch_num}")
        try:
            soup_tmp = BeautifulSoup(raw_html, "lxml")
            h = soup_tmp.find(["h1", "h2", "h3"])
            raw_title = h.get_text(strip=True) if h else ""
        except Exception:
            raw_title = ""
        try:
            cleaned_html, _cleaned_text_joined = clean_html(raw_html, eff_start, eff_end)
        except ValueError as ve:
            raise ValueError(f"invalid selector: {ve}") from ve
        # real chapter title: in-content linkless heading, else list title, else raw h1
        in_title = ""
        try:
            soup_clean = BeautifulSoup(cleaned_html, "lxml")
            for _hh in soup_clean.find_all(["h1", "h2", "h3", "h4"]):
                try:
                    if _hh.find(["a", "button", "select"]):
                        continue
                    _t = _hh.get_text(strip=True)
                except Exception:
                    continue
                if _t and _t.strip():
                    in_title = _t.strip()
                    break
        except Exception:
            in_title = ""
        try:
            list_title = _audio_tlm.get(str(url).strip().rstrip("/"), "")
        except Exception:
            list_title = ""
        ch_title = (in_title or list_title or raw_title or f"Chapter {ch_num}").strip()[:200]
        if not ch_title:
            ch_title = f"Chapter {ch_num}"
        try:
            block_lines = html_to_block_lines(cleaned_html)
        except Exception:
            block_lines = []
        cleaned_text = "\n".join(block_lines) if block_lines else (_cleaned_text_joined or "")
        try:
            filtered_text, removed = apply_filters(cleaned_text or "", filters)
            if removed:
                logs.append(f"cleaned chapter {ch_num} removed {removed} lines")
        except Exception:
            filtered_text = cleaned_text or ""
        filtered_text = (filtered_text or "").strip()
        if not filtered_text:
            logs.append(f"warning: chapter {ch_num} has no text after cleaning, skipped")
            continue
        out.append((ch_num, ch_title, filtered_text))
    if not out:
        raise ValueError("no chapters with text to convert")
    return out


def build_audio(
    novel_url: str,
    from_idx: int | None = None,
    to_idx: int | None = None,
    title: str | None = None,
    output_dir: str | Path | None = None,
    filters: List[Dict[str, Any]] | None = None,
    cache_dir: str | Path | None = None,
    chapter_urls: List[str] | None = None,
    start_selector: str | None = None,
    end_selector: str | None = None,
    voice: str = "en-US-AndrewNeural",
    rate: str | None = None,
    engine: str | None = None,
    local_voice: str | None = None,
    parallel: int = 3,
    retries: int = 5,
    chunk_size: int = 3500,
    audio_format: str = "m4b",
    keep_parts: bool = False,
    keep_mp3: Optional[bool] = None,
    auto_boilerplate: bool | None = None,
    audio_bitrate: str | None = None,
    on_part_status: Optional[Callable[[dict], None]] = None,
    on_log: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[int, int], None]] = None,
    on_phase: Optional[Callable[[dict], None]] = None,
) -> Dict[str, Any]:
    """Build chapter MP3s + optional single-file audiobook from cached chapters.

    Returns {audio_dir, chapter_count, part_count, chapters, audiobook, logs,
    ffmpeg, from, to, slug}. Raises ValueError / AdapterError(CACHE_MISS).
    Synchronous except TTS: runs run_part_jobs on a private event loop
    (mirrors the runTtsJobs sidecar pattern).
    """
    import asyncio

    # Validate novel_url (host allowlist mirrors build_epub)
    if not isinstance(novel_url, str) or not novel_url.strip():
        raise ValueError("url must be non-empty")
    novel_url = novel_url.strip()
    if not re.match(r"^https?://", novel_url, re.I):
        raise ValueError("url must be http(s)")
    try:
        from urllib.parse import urlparse

        host = (urlparse(novel_url).hostname or "").lower().rstrip(".")
        if not host:
            raise ValueError("url must contain host")
        if not (host == "novelphoenix.com" or host == "www.novelphoenix.com" or host.endswith(".novelphoenix.com")):
            from core.ports import AdapterError

            raise AdapterError(f"LIST_FAILED: unsupported host {host}", code="LIST_FAILED")
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(str(e)) from e

    # Title / voice / knobs
    if isinstance(title, str):
        title = title.strip()[:200] or None
    else:
        title = None
    if not isinstance(voice, str) or not voice.strip():
        raise ValueError("voice must be non-empty")
    voice = voice.strip()[:100]
    if rate is None:
        try:
            from core.config import load_store  # dynamic, no cycles

            rate = load_store().get("rate", "+0%")
        except Exception:
            rate = "+0%"
    from core.tts import normalize_tts_rate

    rate = normalize_tts_rate(rate)
    if engine is None or local_voice is None:
        _store_engine: dict = {}
        try:
            from core.config import load_store  # dynamic, no cycles

            _store_engine = load_store() or {}
        except Exception:
            _store_engine = {}
        if engine is None:
            engine = _store_engine.get("engine", "auto") if isinstance(_store_engine, dict) else "auto"
        if local_voice is None:
            local_voice = _store_engine.get("localVoice") if isinstance(_store_engine, dict) else None
    engine = engine.strip().lower() if isinstance(engine, str) else "auto"
    if engine not in ("auto", "edge", "local"):
        engine = "auto"
    if isinstance(local_voice, str):
        local_voice = local_voice.strip() or None
    else:
        local_voice = None
    try:
        parallel = max(1, min(6, int(parallel)))  # type: ignore[arg-type]
    except Exception:
        parallel = 3
    try:
        retries = int(retries)  # type: ignore[arg-type]
        if retries < 1:
            retries = 5
    except Exception:
        retries = 5
    try:
        chunk_size = int(chunk_size)  # type: ignore[arg-type]
        chunk_size = max(500, min(5000, chunk_size))
    except Exception:
        chunk_size = 3500
    fmt = (audio_format or "m4b").strip().lower()
    if fmt not in ("mp3", "m4b", "m4a"):
        raise ValueError("format must be mp3, m4b or m4a")
    if audio_bitrate is None:
        try:
            from core.config import load_store as _load_store_br  # dynamic, no cycles

            audio_bitrate = str(_load_store_br().get("audioBitrate", "32k"))
        except Exception:
            audio_bitrate = "32k"
    try:
        from core.tts import _parse_audio_bitrate as _parse_br

        bitrate = _parse_br(audio_bitrate)
    except ValueError as e:
        raise ValueError(str(e)) from e

    from_i = _to_int(from_idx, 1) or 1
    to_i = _to_int(to_idx, None)
    if to_i is None:
        to_i = from_i
    if from_i > to_i:
        from_i, to_i = to_i, from_i
    if (to_i - from_i + 1) > MAX_AUDIO_RANGE:
        raise ValueError(f"range too large (max {MAX_AUDIO_RANGE} chapters per run)")

    if isinstance(output_dir, (str, Path)) and str(output_dir).strip():
        od = str(output_dir).strip()
        if ".." in od or "\0" in od:
            raise ValueError("outputDir invalid")
    else:
        od = None
    # CWD-robust absolute path: when the GUI exe is launched with an
    # unwritable CWD (e.g. C:\Windows\System32), ./output falls back to
    # ~/Documents/speak-epub/output instead of dying with WinError 5.
    # The GUI opener scope + file:// fallback need absolute paths anyway.
    out_base = resolve_output_dir(od)

    filt = _load_filters(filters)
    logs: List[str] = []

    desired = _resolve_audio_urls(novel_url, from_i, to_i, chapter_urls, cache_dir)
    if len(desired) > MAX_AUDIO_RANGE:
        raise ValueError(f"range too large (max {MAX_AUDIO_RANGE} chapters per run)")
    chapters = _chapter_texts(desired, from_i, cache_dir, filt, start_selector, end_selector, logs, novel_url)

    # Auto-boilerplate (same detection as EPUB so listeners skip headers too)
    if auto_boilerplate is None:
        try:
            from core.config import load_store  # dynamic, no cycles

            auto_boilerplate = bool(load_store().get("autoBoilerplate", True))
        except Exception:
            auto_boilerplate = True
    if auto_boilerplate and len(chapters) >= 2:
        try:
            from core.filters import apply_filters as _apply_text_filters
            from core.filters import detect_boilerplate as _detect_bp

            auto_f = _detect_bp([t for _, _, t in chapters]) or []
        except Exception as e:
            logs.append(f"boilerplate detect error: {e}")
            auto_f = []
        if auto_f:
            logs.append(f"boilerplate templates: {len(auto_f)}")
            cleaned_chapters: List[ChapterText] = []
            for _n, _t, _x in chapters:
                try:
                    _x2, _rem = _apply_text_filters(_x, auto_f)
                    if _rem:
                        logs.append(f"boilerplate removed {_rem} line(s) chapter {_n}")
                    cleaned_chapters.append((_n, _t, _x2.strip() or _x))
                except Exception as e:
                    logs.append(f"boilerplate strip error chapter {_n}: {e}")
                    cleaned_chapters.append((_n, _t, _x))
            # drop chapters left empty after stripping (pure-chrome fragments)
            chapters = [(n, t, x) for n, t, x in cleaned_chapters if x.strip()]
            if not chapters:
                raise ValueError("no chapters with text to convert")
    elif auto_boilerplate:
        logs.append("boilerplate skipped (need 2+ chapters)")

    slug = sanitize_filename(title or "book", fallback="book", max_len=60)
    audio_dir = out_base / f"{slug}_audiobook"
    audio_dir.mkdir(parents=True, exist_ok=True)

    # fail fast / warn upfront: truncation auto-repair, chapter merging and
    # M4B/M4A all need ffmpeg — better to know before hours of synthesis
    if not ffmpeg_available():
        if str(engine or "").strip().lower() == "local":
            raise RuntimeError("local TTS engine requires ffmpeg on PATH — install it and re-run")
        logs.append("warning: ffmpeg not found on PATH — chapter merging, M4B/M4A and truncation auto-repair are disabled")

    plans, jobs = build_generation_plan(chapters, str(audio_dir), chunk_size, rate=rate)
    logs.append(f"queued {len(jobs)} TTS part job(s) for {len(chapters)} chapter(s)")

    def _emit_log(line: str) -> None:
        logs.append(line)
        if len(logs) > 2000:
            del logs[: len(logs) - 2000]
        if on_log:
            try:
                on_log(line)
            except Exception:
                pass

    def _emit_phase(phase: str, done: int = 0, total: int = 0) -> None:
        payload = {"phase": phase, "done": done, "total": total}
        if on_phase:
            try:
                on_phase(payload)
            except Exception:
                pass

    # run_part_jobs is async; drive it on a private loop (sidecar-safe,
    # same pattern as the runTtsJobs RPC branch)
    async def _runner() -> None:
        await run_part_jobs(
            jobs, voice, parallel, retries,
            on_part_status=on_part_status, on_log=_emit_log, on_progress=on_progress,
            rate=rate, adaptive=True, engine=engine, local_voice=local_voice,
        )

    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed loop")
    except Exception:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    # Long silent stretches (TTS gaps between parts, per-chapter merges, and
    # especially the final multi-minute M4B re-encode) must not look dead:
    # the desktop sidecar times out after seconds of silence. Heartbeat lines
    # keep the stream alive; the Rust reader additionally tolerates gaps.
    with _heartbeat_scope(_emit_log):
        try:
            if loop.is_running():
                import threading as _th

                box: Dict[str, Any] = {}
                exc_box: Dict[str, Any] = {}

                def _run_in_new_loop() -> None:
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    try:
                        new_loop.run_until_complete(_runner())
                        box["ok"] = True
                    except Exception as e:  # noqa: BLE001
                        exc_box["e"] = e
                    finally:
                        new_loop.close()

                th = _th.Thread(target=_run_in_new_loop, daemon=True)
                th.start()
                th.join(timeout=1800)
                if th.is_alive():
                    raise TimeoutError("TTS timed out after 1800s; partial files kept, re-run to resume")
                if "e" in exc_box:
                    raise exc_box["e"]
            else:
                loop.run_until_complete(_runner())
        except RuntimeError as rte:
            if "already running" in str(rte).lower() or "closed" in str(rte).lower():
                asyncio.run(_runner())
            else:
                raise

        audio_entries = finalize_chapter_audio(
            plans,
            keep_parts=keep_parts,
            on_chapter=lambda d, t: _emit_phase("merging", d, t),
        )
        if not audio_entries:
            raise RuntimeError("TTS produced no audio files")

        chapter_infos = [
            {"number": num, "title": t, "path": p} for num, t, p in audio_entries
        ]

        audiobook: Optional[Dict[str, Any]] = None
        if fmt in ("m4b", "m4a"):
            book_title = f"{slug}_chapters_{from_i:03d}_to_{to_i:03d}"
            _emit_phase("multiplex", 0, 1)
            _emit_log(f"building {fmt.upper()} file...")
            build_m4b(
                str(audio_dir),
                audio_entries,
                book_title,
                fmt,
                bitrate=bitrate,
                on_progress=lambda d, t: _emit_phase("multiplex", d, t),
                on_probe=lambda d, t: _emit_phase("probing", d, t),
            )
            out_path = audio_dir / f"{book_title}.{fmt}"
            if out_path.is_file():
                try:
                    size = out_path.stat().st_size
                except OSError:
                    size = 0
                audiobook = {"path": str(out_path), "size": size, "format": fmt}
                # honor keepMP3=false: single file replaces chapter MP3s
                if keep_mp3 is None:
                    try:
                        from core.config import load_store  # dynamic, no cycles

                        keep_mp3 = bool(load_store().get("keepMP3", True))
                    except Exception:
                        keep_mp3 = True
                if keep_mp3 is False:
                    for _num, _t, p in audio_entries:
                        try:
                            if Path(p).is_file() and Path(p).resolve() != out_path.resolve():
                                Path(p).unlink()
                        except OSError:
                            continue
                    logs.append("chapter MP3s removed (keepMP3=false)")
            else:
                logs.append(f"warning: expected {fmt.upper()} not found after ffmpeg (see warnings above)")

    return {
        "audio_dir": str(audio_dir),
        "chapter_count": len(chapters),
        "part_count": sum(len(split_text_for_tts(t, chunk_size)) for _, _, t in chapters),
        "chapters": chapter_infos,
        "audiobook": audiobook,
        "format": fmt,
        "bitrate": bitrate,
        "voice": voice,
        "ffmpeg": ffmpeg_available(),
        "logs": logs,
        "from": from_i,
        "to": to_i,
        "slug": slug,
    }


__all__ = ["build_audio", "MAX_AUDIO_RANGE"]
