---
id: SPEC-speak-epub
companions:
  - _bmad-output/planning-artifacts/ux-designs/ux-speak-epub-2026-08-27/DESIGN.md
  - _bmad-output/planning-artifacts/ux-designs/ux-speak-epub-2026-08-27/EXPERIENCE.md
  - _bmad-output/planning-artifacts/architecture/architecture-speak-epub-2026-08-27/ARCHITECTURE-SPINE.md
sources:
  - _bmad-output/planning-artifacts/briefs/brief-speak-epub-2026-08-27/brief.md
  - _bmad-output/planning-artifacts/briefs/brief-speak-epub-2026-08-27/addendum.md
  - Speak-EPUB-1.0.0/speak.py
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# Speak EPUB — Scraper → EPUB → Audiobook

## Why

A pain to solve and an opportunity to claim. Readers want web-fiction (starting NovelPhoenix) as clean EPUB for e-readers first, audiobook second, but sites offer neither and abandoned scrapers fail on current layouts, noisy HTML (1–3 subscription-nag lines per chapter plus nav/footer chrome), and bans after 4–5 rapid fetches even manually. Speak EPUB already converts EPUB → M4B via Microsoft Edge TTS (chunking at sentence boundaries, parallel PartJob queue, FFmpeg markers) but starts too late. The gap is a local, MIT, polite end-to-end flow: paste URL or title → per-site counts → pick source/range → fetch politely with resume → clean via per-adapter selectors + preview + user filters → build validated EPUB → optionally produce M4B. Without this, users copy-paste manually or give up on TTS and audio inherits chrome.

## Capabilities

- **CAP-1 — Find**
  - **intent:** Reader can find a novel by pasting its URL or typing its title and seeing per-site matches with chapter counts to pick the source.
  - **success:** Title search returns correct matches with `site | chapters | link` in <5s per site in parallel; URL fallback guessing picks adapter for unknown domain; wrong title yields empty state with URL hint.

- **CAP-2 — Choose**
  - **intent:** Reader can fetch the chapter list politely and pick an exact range via `from–to` inputs plus checkboxes with total count visible.
  - **success:** Chapter list loads with polite indication; entering `1–30` selects exactly 30 of 142 and syncs checkboxes; bulk Shift-select and clamping to 1..N work; double-click on row opens Preview for that chapter.

- **CAP-3 — Fetch & Clean**
  - **intent:** System can fetch only the chosen chapters politely with cache and resume and isolate body via per-adapter start/end CSS selectors plus heuristic fallback with preview-correctable bounds and strip user-defined filter phrases.
  - **success:** 100-chapter novel scrapes sequentially with 3–5s + jitter (10s safe) without 429/ban; adaptive backoff on 429 emits `throttleChanged`; raw HTML cached per `sha1(url)` (Core-owned); preview isolates body correctly >95% without fix, manual selector edit re-parses live; bounded range (e.g., 20–100) fetches only missing via cache diff; open-ended to-end re-validates list and detects new chapters.

- **CAP-4 — Build EPUB**
  - **intent:** System can assemble a validated EPUB (title, author, cover if available, TOC) as a standalone artifact with filter phrases applied once at build.
  - **success:** 20-chapter sample is `epubcheck` clean, cover/TOC/metadata correct, 0 subscription-nag lines after filters (plain `contains` + regex); raw cache still contains nags (test invariant).

- **CAP-5 — Make Audio**
  - **intent:** System can turn the built EPUB into per-chapter MP3s and a single M4B/M4A with chapter markers using sentence-boundary chunking and a global parallel queue.
  - **success:** 10-chapter sample builds M4B with correct chapter markers and durations (ffprobe) in <1h on parallel 3; chunking respects `max_chars=3500`; `PartJob` queue is global across chapters in reading order; retries 5 with backoff `min(20, 2*attempt)` handle Edge throttling; `_parts/*.mp3` are skipped on re-run.

- **CAP-6 — Control & Persist**
  - **intent:** Reader can see live per-chapter and per-part progress with logs and throttle tier and persist all settings across restarts to control outputs.
  - **success:** Queue shows `queued/fetching/cleaning/TTS/merging/done/error` per chapter plus expandable parts, global elapsed + throttle badge, `skipped N, fetching X–Y` on resume; Settings (voice, rate, parallel 2–3, chunk-size, retries, scrape delay, safe mode) and Filters (plain/regex) and keep switches (EPUB/MP3/M4B) persist via single local JSON and mirror CLI flags.

## Constraints

- Politeness is non-negotiable: sequential fetch only, `3–5s + jitter` default and `10s` safe, adaptive on 429 with jitter and exponential retry cap 20s; no parallel scrape even though TTS runs parallel 2–3.
- Local-first: zero data leaves device after fetch; offline after fetch must work for preview, EPUB build, and audio; single desktop artifact for Win/macOS/Linux via Tauri; Windows double-click shortcut (`Run-SpeakEPUB-Tauri.cmd` pattern) retained.
- Brownfield invariants ratified: `split_text_for_tts(max_chars=3500)` at sentence boundaries, `PartJob` frozen dataclass with global queue, `extract_chapters` spine-order numbering + `<100 chars` skip, `venv` at `Speak-EPUB-1.0.0/venv` (`Scripts/python.exe` Win / `bin/python` macOS/Linux via `core/config.py` OS detection, never bare `python`), FFmpeg/ffprobe required for M4B via `shutil.which`.
- Architecture is `Modular Pipes-and-Filters + Ports & Adapters`: `GUI → Core → Pipeline` and `Core → ScraperPort → Adapter`; `ScraperPort` defines `search/listChapters/fetchChapter/getSelectors`; one event bus `chapterStatus/partStatus/logLine/throttleChanged/done` (no polling); EPUB is the only TTS source.
- UX progressive disclosure: first screen is one input plus pick; advanced throttles/voice/parallel/chunk/filters live behind Settings/Filters; visual identity is `DESIGN.md` tokens (neutral ink + one action blue, 8px rounding).

## Non-goals

- Batch queue of multiple novels (later).
- Logged-session/paywall bypass beyond an experimental hidden `cookie/header` port.
- Auto-update scheduling, cloud sync, mobile companion, >5-site bulk search, collaborative filter sharing, non-Edge TTS engines, DRM.

## Success signal

A reader pastes a title or NovelPhoenix URL, sees per-site counts in <5s, picks a range (e.g., 1–30), gets a locally built `epubcheck`-clean EPUB with 0 nag lines plus, if chosen, a single M4B with accurate chapter markers — all without bans on a 100-chapter run and with correct resume (missing-only vs re-validate) on a second run — validated on a 20-chapter clean sample and a 10-chapter M4B in <1h.

## Assumptions

- UI language auto-detects system locale with i18n key abstraction (`t("find.input.placeholder")`), `en.json` fallback; PL initially included via `pl.json` — decision adopted 2026-08-27 from UX [ASSUMPTION] EN-primary.
- Tauri sidecar transport is JSON-RPC over stdin/stdout (primary) with HTTP localhost fallback if 10-min spike test (`tauri-plugin-shell` + OS-specific venv path) fails; cache key is `sha1(normalized_url)` owned by Core (`core/fetch.py`); `core/config.py` detects OS and resolves `venv/Scripts/python.exe` (Win) vs `venv/bin/python` (macOS/Linux) — AD-4 adopted with spike.
- Tauri starter `create-tauri-app` + React/Vite/Tailwind/shadcn is deferred to implementation — pin exact versions at `cargo add` / `npm view` (core `2.11.5` verified 2026-07-01 remains).

## Open Questions

- Exact M4B chapter marker encoding via FFmpeg chapter metadata — verify `ffprobe` duration ms on Windows before locking `core/merge.py`.

