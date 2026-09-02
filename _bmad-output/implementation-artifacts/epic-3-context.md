# Epic 3 Context: Słuchacz M4B — z EPUB do audiobooka z markerami

<!-- Generated from planning artifacts. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Enable the user to build per-chapter MP3s and a single M4B/M4A with chapter markers from an already-built EPUB, using sentence-boundary chunking and a global parallel queue with resume — delivering a standalone audiobookSecond flow on top of Epic 2 without re-fetching content.

## Stories

- Story 3.1: TTS Chunking + PartJob queue (ratyfikacja brownfield)
- Story 3.2: Edge TTS + parallel 2–3 + retries + _parts skip
- Story 3.3: FFmpeg merge per-chapter + single M4B z markerami

## Requirements & Constraints

- Chunking must split at sentence boundaries with max_chars 3500 via `split_text_for_tts`, hard cut fallback if single sentence >3500, preserve reading order (FR5, NFR4). No truncation — Edge TTS truncates overlong requests.
- PartJob queue must be frozen dataclass with `chapter_number, part_number, part_count, text, output_path, is_final_chapter_file` and global queue in reading order: chapter 40 all parts before 41 (FR5, NFR6 brownfield).
- TTS execution must be parallel 2–3 (global queue, not per-chapter), respect Edge throttling, 5 retries with backoff `min(20, 2*attempt)` and log `retry 1/4` (NFR3, NFR1 no parallel scrape vs TTS parallel 2-3 allowed).
- Parts already on disk at `_parts/*.mp3` must be skipped on re-run (resume), log `skipped _parts/*.mp3` and badge correct (NFR3).
- FFmpeg merge per-chapter via `concat.txt -c copy` in book order; if FFmpeg missing keep parts and warn with `ffmpeg -version` hint (FR5, NFR6).
- Single M4B/M4A must contain chapter markers via FFmpeg chapter metadata, duration verified via ffprobe ms, name `<slug>_chapters_<from>_to_<to>.m4b`, 10-chapter sample <1h on parallel 3 (FR5, NFR2).
- EPUB is sole TTS source via `extract_chapters` (AD-8); brownfield reuse of existing `speak.py` PartJob and spine-order numbering.
- Local-first: zero data leaves device after fetch; audio build works offline (NFR5). Single desktop bundle, Windows double-click shortcut.

## Technical Decisions

- Pipes-and-Filters + Ports & Adapters (AD-1) — `core/tts.py` ratifies `speak.py:split_text_for_tts` and `PartJob`, `core/merge.py` owns FFmpeg concat + M4B markers. No adapter involvement.
- EPUB as intermediate invariant (AD-8) — build EPUB first gated on epubcheck, then feed to `extract_chapters → split_text_for_tts → PartJob` unified path.
- Event bus single typed (AD-6) — `partStatus` carries PartJob fields; GUI renders queue progress auto-scroll without polling (Epic 3 uses basic progress, full live expansion in Epic 4).
- Config persistence (AD-10) single `store.json` via tauri-plugin-store mirrors `voice, rate, parallel 2-3, chunk-size 3500, retries 5` — GUI writes on blur, Core reads on start.
- Resume via cache key `sha1(normalized_url)` owned by Core (AD-9) already; TTS resume is `_parts` existence check owned by `core/tts.py`/`core/merge.py`.
- Stack: Python 3.10+, edge-tts 7.2.8, FFmpeg/ffprobe via `shutil.which`, Tauri 2.11.5, React 18/TS5/Vite6/Tailwind4.

## UX & Interaction Patterns

- Queue/Progress minimal row per chapter: status pill `queued/TTS/merging/done/error` + mini progress `progress-track`, expand to part dots `_parts/*.mp3` deferred to Epic 4 but dots shown for verification.
- Global header elapsed time + throttle badge already from Epic 2; TTS respects same politeness tier display.
- Result Output cards for MP3/M4B: path mono, size, markers count, duration, Play + Open folder via Tauri opener, keep switches reflection (EPUB/MP3/M4B).
- States: TTS throttled retry toast warning, FFmpeg missing warning with PATH hint, no data loss on retry.

## Cross-Story Dependencies

- Story 3.1 is foundation gate — `split_text_for_tts` 3500 sentence-boundary + frozen PartJob global reading-order queue must land before any TTS execution or merge.
- Story 3.2 depends on 3.1 queue — implements Edge TTS parallel 2-3 with 5 retries and `_parts` skip for resume; consumes queue deterministically (1,2,3 first, then 4 on free slot).
- Story 3.3 depends on 3.2 parts — FFmpeg concat per-chapter then single M4B with chapter markers and ffprobe verification; produces final audio artifact and Result M4B card. Consumes keep switches and validates 10-chapter <1h benchmark.
- Epic 3 builds on Epic 2 EPUB artifact via `extract_chapters`; no fetch/clean rework. Epic 4 will expand live queue per part and full Settings/Filters persistence on top.
