# Addendum — Speak EPUB Brief

Captures depth that belongs downstream (PRD/architecture) or was parked.

## Rejected alternatives & rationale

- **100% Python GUI (CustomTkinter/PySide6)** vs **Python core + Tauri GUI**: PySide is simpler to maintain for Python-only contributors but never as nice as web design system and heavier to package cross-platform. Chose hybrid: Python sidecar retains `ebooklib`, `edge-tts`, `lxml` and existing `speak.py:split_text_for_tts`/`tts_text_to_mp3`; Tauri gives nice cross-platform UI with ~10MB WebView. Electron considered heavier (~150MB) — leave as fallback if Tauri signing/notarization becomes painful.
- **Node-only rewrite**: would lose `ebooklib` EPUB builder and proven chunk/merge/resume logic. Keep Python for scraping/TTS, expose via subprocess/IPC.

## Technical constraints & assumptions

- NovelPhoenix ban threshold: ~4–5 rapid requests (observed even manual). Mitigation: 3–5s + jitter default, 10s safe mode, adaptive backoff on 429, cache/resume. Validate with real 100-chapter run before locking defaults.
- Content boundaries: per-adapter CSS selectors (`article`/`div.chapter-content`) plus heuristic fallback; preview pane required to survive layout drift. Filters: plain `contains` + regex, applied at EPUB stage so EPUB is clean; `_parts` and chapter MP3 inherit cleanliness via TTS pipeline.
- Title search: titles only (not author/tag), returns `site | chapters | link` table. Aggregator queries supported sites in parallel <5s. Fallback adapter guessing tries generic selectors when URL domain unknown.
- Logged-session: design interface to accept `cookie/header` but hide behind experimental flag in v1; NovelPhoenix needs no auth, other sites will.

## Parked roadmap (Scope Out detail)

- Batch queue of multiple novels, auto-update detection for new chapters, scheduling, cloud sync, mobile companion, >5-site bulk search, collaborative filter sharing, non-Edge TTS engines, DRM.

## Options considered

- Default scrape delay 10s static vs adaptive 3–5s + jitter. Chose adaptive for UX but keep 10s safe mode.
- Filter scope: EPUB-only vs EPUB+audio. Chose EPUB-stage so audio automatically clean.

## Downstream handoff notes

- PRD should define adapter interface (`listChapters(url)`, `fetchChapter(url)`, `search(title)`), selector test harness, and Tauri<->Python IPC (e.g., sidecar binary vs `python -m speak` subprocess).
- Architecture must ratify existing `Speak-EPUB-1.0.0/speak.py` chunking, `PartJob` queue, FFmpeg merge, and `Run-SpeakEPUB.cmd` pattern for new `Run-SpeakEPUB-Tauri.cmd`.
