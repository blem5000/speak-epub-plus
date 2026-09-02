---
title: "Speak EPUB - NovelPhoenix Scraper + Audiobook"
status: ready
created: 2026-08-27
updated: 2026-08-27
---

# Product Brief: Speak EPUB — NovelPhoenix → EPUB → Audiobook

## Executive Summary

Speak EPUB is a local, open-source desktop app that turns web fiction — starting with NovelPhoenix — into proper audiobooks with a clean intermediate EPUB. Paste a novel URL or just its title, see matches with chapter counts per site and pick the source, then choose a chapter range; the app scrapes politely (3–5s default delay + jitter, 10s safe mode), builds a validated EPUB (metadata, cover, TOC), and reuses the proven Edge TTS pipeline to produce chapter MP3s and a single M4B/M4A with chapter markers. A cross-platform, nice GUI (Python core + Tauri GUI recommended) exposes two throttles (scrape delay + TTS rate), voice selection, and keep-switches for EPUB/MP3/M4B, plus filters to strip subscription prompts and content-boundary detection to exclude site chrome. An adapter architecture lets new sites be added without touching the core, and a title-search aggregator with fallback adapter guessing finds stories across supported sites. Everything runs locally, resumes after failure, ships with a Windows double-click shortcut (like `Run-SpeakEPUB.cmd`), and respects site politeness to avoid bans.

## The Problem

Readers want web fiction as EPUB for e-readers first, audiobook second — but sites like NovelPhoenix offer neither. Existing EPUB scrapers are abandoned, fail on current layouts, and throw frequent errors; users fall back to manual copy-paste or give up on TTS entirely. Raw scraped HTML is noisy on many sites (1–3 lines per chapter: subscription prompts, stray symbols, nav/footer chrome) and without content-boundary detection that noise would be read aloud. Aggressive fetching triggers real bans — even manual browsing of 4–5 chapters quickly can cause a temporary ban — so a naive scraper is quickly blocked. Speak EPUB already solves EPUB→audio (Edge TTS, chunking, resume, M4B markers) but starts too late; there is no local, open-source, polite end-to-end flow from URL/title → clean EPUB → optional audio with chapter-range choice, throttling, filters, and resume.

## The Solution

A local desktop app (Python core + Tauri GUI, with a Windows double-click shortcut) completes the missing first half:

1. **Find** — paste a novel URL or type a title. Title-search aggregator queries supported sites in parallel, shows `site | title match | chapters | link` and lets the user pick; fallback adapter guessing handles unknown URLs.
2. **Choose** — fetches the chapter list politely and presents it with `from–to` range picker + checkboxes and total count.
3. **Fetch & clean** — scrapes only the chosen range with configurable delay (default 3–5s + jitter, 10s safe mode) that adapts on 429/retry, caches raw HTML for resume, isolates content via per-adapter start/end selectors with heuristic fallback, provides a preview pane where the user can correct boundaries when layout changes, and strips user-defined filter phrases (plain contains + regex, 1–3 lines per chapter) applied at EPUB build stage plus nav/footer chrome.
4. **Build EPUB** — assembles a validated EPUB (title, author, cover if available, TOC) as a standalone artifact even without audio, and reuses the existing `speak.py` pipeline for the rest.
5. **Make audio (optional)** — feeds the EPUB through the proven TTS flow: sentence-boundary chunking (`--chunk-size`), global parallel queue (`--parallel` 2–3), Edge TTS with voice + rate control, retries/backoff, merging via FFmpeg into per-chapter MP3s and/or single M4B/M4A with chapter markers.
6. **Control** — Tauri GUI shows live queue/progress per chapter & part, logs, keep-switches (`keep EPUB / keep MP3 / build M4B-M4A`), a Settings window persisting all CLI-equivalents (`--voice`, `--rate`, `--parallel`, `--chunk-size`, `--retries`, scrape delay, keep flags) to local config, and a dedicated Filters window; conditional resume fetches only missing chapters for a bounded range (e.g., 20–100) and re-validates the list when fetching to the end to detect new chapters.

## What Makes This Different

No invented defensibility — the advantage is execution and upkeep. Abandoned EPUB scrapers break on layout changes, lack politeness delays, and have no resume, filters, or audio path; online converters require uploads, lack chapter-range control, and keep data off-device. Speak EPUB wins by being (1) polite and resilient — adaptive delay/jitter, cache/resume, and preview-correctable boundaries that survive the 4–5-chapter ban threshold; (2) local and open-source (MIT) — nothing leaves the machine, community can maintain adapters; (3) extensible — new sites are adapter plugins plus title-search aggregation, not forks. If adapter upkeep slows, the advantage fades, so the project ships with selector tests and a filter/bounds editor to keep fixes cheap.

## Who This Serves

Primary: **Web-fiction readers** across sites (NovelPhoenix first, others via adapters) who want stories offline on e-readers first, audiobook second. They can run a desktop app, value local control, and are blocked by broken scrapers, noisy exports, and bans. Success = paste title/URL → see chapter counts per site → pick range → get clean EPUB and, if chosen, M4B/MP3 without manual cleanup.

Secondary: **Open-source contributors** maintaining adapters/filters. Success = add a site via a small adapter + selectors + tests, without touching the core.

EPUB-only without audio is a first-class mode, not a fallback.

## Success Criteria

User: (1) Title search returns correct matches with chapter counts per site in <5s; (2) 100-chapter novel scrapes in polite mode without 429/ban; bounded resume fetches only missing chapters, open-ended re-validates and detects new ones; (3) EPUB validates (`epubcheck` clean) with correct TOC/cover/metadata and 0 subscription-nag lines on a 20-chapter sample after filters; (4) Content preview isolates body correctly for >95% chapters without manual fix, manual correction works when needed; (5) Audio end-to-end: 10-chapter sample builds M4B with chapter markers in <1h on parallel 3 via reused pipeline; (6) Settings and filters persist across restarts.

Project: (1) NovelPhoenix adapter stays green on CI selector tests; (2) New adapter added in <1 day via documented interface; (3) Windows double-click launch works and app runs on Win/macOS/Linux via Tauri; (4) Zero data leaves device after fetch (local-only).

## Scope

**In v1:** NovelPhoenix adapter (list + fetch + cover/metadata), title-search aggregator with `site | chapters | pick` + URL fallback guessing, chapter-list fetch + `from–to` + checkboxes, polite fetch (3–5s + jitter default, 10s safe, adaptive on 429, cache/resume conditional), content-boundary selectors + preview pane, user filters (plain + regex, applied to EPUB), EPUB build (TOC/metadata/cover), Tauri GUI (Python core sidecar) with progress per chapter/part, two throttles, voice picker, keep-switches (EPUB/MP3/M4B), Settings window (all `--voice/--rate/--parallel/--chunk-size/--retries/delay/keeps`) with persistence, Filters window, reuse of existing TTS/M4B pipeline, Windows double-click shortcut, cross-platform Win/macOS/Linux, selector tests + `epubcheck` in CI.

**Out v1 (parked):** Batch queue of multiple novels (later), logged-session/paywall bypass — designed for, hidden as experimental cookie/header for power users in v1, auto-update scheduling, cloud sync, mobile app, >5-site bulk search, collaborative filter sharing, non-Edge TTS engines, DRM.

## Vision

If it succeeds, Speak EPUB becomes the community-maintained, local-first hub for web fiction → EPUB/audio: a small core + dozens of community adapters (NovelPhoenix first, then the long tail), each with tests and filters shared via simple PRs. Title search becomes a unified discovery layer, the GUI stays polite and repairable when sites drift, with CLI parity (`speak.py` headless remains) and GUI for newcomers (double-click on Windows, Tauri everywhere). Every story you love lives on your device as a clean EPUB and a proper M4B — no cloud, no lock-in.
