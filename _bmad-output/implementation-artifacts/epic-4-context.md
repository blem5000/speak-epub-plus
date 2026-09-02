# Epic 4 Context: Desktopowa Kontrola — pełny live, persist i poler UX

<!-- Generated from planning artifacts. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Deliver full desktop control on top of the fetch/clean/EPUB (Epic 2) and TTS/M4B (Epic 3) foundations: expanded live per-chapter + per-part queue with logs and throttle badge, keep switches, complete Settings/Filters with plain+regex support and persistence plus i18n auto-detect, conditional resume that fetches only missing for bounded ranges and re-validates for open-ended, and polished state treatments with WCAG 2.2 AA and responsive layout so the app feels complete and all controls survive restarts.

## Stories

- Story 4.1: Live Queue expansion + event bus + throttle/badge + log
- Story 4.2: Settings form + persist store.json + i18n auto-detect
- Story 4.3: Filters window pełny + integracja z Preview + EPUB gate
- Story 4.4: State treatments + a11y AA + responsive & platform

## Requirements & Constraints

- Live control must show per-chapter row with status pill (queued/fetching/cleaning/TTS/merging/done/error) plus mini progress track and expandable part dots for `_parts/*.mp3`, global elapsed time and throttle badge (polite/safe), log pane with incremental lines and throttleChanged events, auto-scroll to live row, no polling (FR6).
- Keep switches for EPUB / MP3 / M4B must decide which artifacts remain and be reflected in Result cards (path mono, size, marker count, Open folder and Play) (FR6).
- Settings must group Audio (voice Select + rate Slider paired with numeric), Performance (parallel 2-3, chunk-size 3500, retries 5), Scrape (delay preset 3-5s + jitter / 10s safe + custom + safeMode), Outputs (keepEPUB/MP3/M4B) with helper text, persist on blur with toast, no save button, mirroring CLI flags across restarts (FR6, NFR6).
- Filters must support plain contains and regex with type badge, phrase, scope, delete, add via Input + type toggle, live average lines removed, persist on blur to filters array; Preview chips show lines removed per chapter, Original vs Cleaned diff visible (FR6 + FR3 filter gate).
- Filter correctness invariant must hold: raw HTML cache never filtered, filters applied once at EPUB build after selector isolation; TTS inherits cleanliness because it reads the built EPUB (NFR4, AD-2/AD-8).
- Resume must be conditional: bounded range diffs desired range against cache and fetches only missing with badge and log "pominięto N, pobieram X-Y" and skipped `_parts` logged; open-ended re-validates chapter list to detect new chapters then fetches only new (NFR3).
- Politeness must remain sequential fetch with adaptive backoff on 429 (increment to safe 10s, jitter, exponential cap 20s) emitting throttleChanged for badge and toast; no parallel scrape even though TTS runs parallel 2-3 (NFR1).
- Local-first and cross-platform: zero data leaves device after fetch; preview, EPUB build and audio work offline after fetch; single desktop bundle per OS with Windows double-click shortcut; FFmpeg/ffprobe presence checked and missing warned without breaking parts (NFR5, NFR6).
- i18n must auto-detect system locale and use keyed translation files with fallback, no hard-coded UI strings; language is GUI table not architecture.
- Success is full live feedback and persistence — queue/logs/badge correct including resume, settings and filters survive restarts, and EPUB remains epubcheck clean with 0 nag lines after filters on 20-chapter sample (NFR4).

## Technical Decisions

- Paradigm Modular Pipes-and-Filters + Ports & Adapters, dependency direction GUI (Tauri+React) -> Core -> Pipeline and Core -> Port -> Adapter; pipeline never imports concrete adapters, adapters import nothing from pipeline; ScraperPort ABC in `core/ports.py` is enforcement point with import linter (AD-1).
- Single typed event bus via Tauri emit/listen with no polling: `chapterStatus`, `partStatus`, `logLine`, `throttleChanged`, `done`; `partStatus` carries PartJob fields (chapter_number, part_number, part_count, is_final_chapter_file) so GUI renders exactly what Core emits (AD-6).
- State ownership: Core owns chapter list, raw cache (`_cache/<sha1>/raw.html` with `sha1(normalized_url)` owned by Core), cleaned text, EPUB manifest, PartJob queue and progress derivation including resume badge; GUI is stateless view plus persisted config mirror; adapters own start/end selectors and heuristic fallback (AD-5, AD-9).
- Politeness ownership in fetcher: delay tiers 3-5s + jitter default and 10s safe, Core decides tier on 429 and emits throttleChanged; GUI only displays (AD-3).
- Filtering stage fixed at EPUB build after selector isolation; TTS reads the built EPUB via `extract_chapters -> split_text_for_tts` so no second filter path and truncation logic stays unified; raw cache test is filter phrase present in raw but absent in EPUB (AD-2, AD-8).
- Config persistence single local JSON via tauri-plugin-store (`store.json`) mirroring all CLI equivalents (voice, rate, parallel 2-3, chunk-size 3500, retries 5, scrapeDelay, safeMode, keep* , filters[]); GUI writes on blur, Core reads on start; OS-aware venv path in `core/config.py` via tauri-plugin-shell and JSON-RPC stdin/stdout primary with HTTP fallback after 10-min spike (AD-4, AD-10).
- Selector boundary: per-adapter start/end selectors are source of truth, heuristic `article/div.chapter-content` only fallback never auto-overwrites adapter selectors; user correction stored as overlay `adapters/overrides/<site>.json` with live re-parse and Reset to adapter (AD-7).
- Stack for this epic: Python 3.10+, Tauri 2.11.5 (api 2.11.1, cli 2.11.4), React 18 + TypeScript 5 + Vite 6 + Tailwind 4 + shadcn/ui, tauri-plugin-store and tauri-plugin-shell, edge-tts 7.2.8, FFmpeg/ffprobe via `shutil.which`.

## UX & Interaction Patterns

- Tokens are the visual contract from design: neutral background/foreground/muted/border/input plus single action blue accent and status success/warning/destructive, typography display 28/20 heading 16 body 14/13 mono JetBrains 12, rounding 6/8/12/16/full and spacing 4..48 exposed as CSS vars/Tailwind; dark mode follows `prefers-color-scheme`, no manual toggle in v1.
- Queue/Progress list: per-chapter row status pill queued/fetching/cleaning/TTS/merging/done/error + mini progress `progress-track`, expand to part dots `_parts/*.mp3`, global header elapsed + throttle badge polite/safe, auto-scroll to live row, log pane mono `role=log` with `aria-live=polite`.
- Settings form: grouped sections Audio/Performance/Scrape/Outputs, label heading with control right-aligned (Select/Switch/Slider), helper body-sm muted, spacing md between groups, Slider+number paired for rate, persist on blur with toast "Zapisano", no save button; champion progressive disclosure — first screen only Input+Pick+range+Start, advanced behind gear.
- Filters surface: table with type badge plain/regex, phrase, scope, delete, add via Input + toggle, live "usuwa średnio 2 linie/rozdz."; Preview split 40/60 with tabs Original/Cleaned, editable start/end selector inputs mono with live re-parse and "Reset do adaptera", filter chips with badge + text + x showing per-chapter removal.
- State treatments: cold launch focuses Find input; searching shows input spinner + 3 skeleton rows "Przeszukuję NovelPhoenix + inne…"; no results shows display-sm "Brak wyników dla 'X'" + "Wklej URL" CTA; chapter list loading 6-row skeleton "Pobieram listę rozdziałów (polite)…"; 429 throttled toast warning "Zwolnienie — 429, zwiększam opóźnienie do 10s (safe)" with retry countdown; ban error row "Przerwa — wykryto ograniczenie. Wznów później." with resume hint and cached data kept; empty preview "Nie wyizolowano treści — popraw selektory"; offline-after-fetch works locally; build done success pill "Gotowe" with epubcheck badge; FFmpeg missing warning "FFmpeg nie znaleziono — części pozostaną niescalone" with `ffmpeg -version` path hint; resume badge "pominięto N, pobieram X-Y".
- Interaction primitives: keyboard Tab cycles Find→table→CTA, Enter confirms pick/range/start, arrows navigate tables with roving tabindex, Space toggles checkbox, Ctrl+A selects all, Esc closes topmost modal with focus trap, Ctrl+Z in selector inputs; mouse row click selects, checkbox for multi, double-click opens Preview, hover reveals eye; banned drag-to-reorder chapters (spine order) and infinite scroll; double-click and Shift bulk select supported where specified.
- Accessibility floor WCAG 2.2 AA: focus rings 2px ring color with AA contrast, keyboard-operable tables, `aria-live` on queue, screen reader announces surface "Wyszukiwanie / Lista 142 / Wybrano 6 / Kolejka 5/10", status pills use text+color+icon never color alone, Esc always closes modal, respects `prefers-reduced-motion`, log pane role=log, focus trap in modals.
- Layout and platform: centered max 960px content, Preview widened 1120px, narrow desktop 900-1199 stacks Preview to single column and keeps table density, window minimum 900px no mobile v1; Tauri drag region on title bar, native open-folder via opener, opt-in native notifications for done/error, no auto-update in v1.

## Cross-Story Dependencies

- Story 4.1 is foundation gate — expanded event bus with partStatus/throttleChanged/logLine and queue rendering must land before Settings, Filters or polish can be verified live; global elapsed, resume badge and auto-scroll are prerequisites.
- Story 4.2 depends on 4.1 bus and defines the persisted config contract (`store.json` keys for voice/rate/parallel/chunk/retries/delay/safeMode/keeps/filters plus i18n key set); Settings persistence and auto-detect locale must exist before Filters window can store filter arrays and before queue can reflect keep/throttle choices.
- Story 4.3 depends on 4.2 persistence and on Epic 2 filter gate (raw unfiltered, EPUB once) — Filters window writes filters[] and Preview integration shows per-chapter chip counts and live averages; Preview selector inputs from 2.2 are reused and must stay compatible with adapter overlay storage.
- Story 4.4 depends on 4.1/4.2/4.3 being present — state treatments, AA keyboard/aria, and responsive breakpoints are verified against the live queue, Settings/Filters modals, and Result cards together; single-column Preview, skeleton/toast/empty/ban states and focus traps only testable when all surfaces exist.
- Epic 4 builds on Epic 2 (polite fetch/cache/preview/filters/EPUB) and Epic 3 (TTS chunk 3500 PartJob parallel 2-3 and FFmpeg M4B markers) without re-implementing them; it only expands visibility and persistence on top, so any change to ScraperPort, cache key, PartJob shape or epubcheck gate in earlier epics requires re-verifying 4.1 queue and 4.3 filter invariants.
