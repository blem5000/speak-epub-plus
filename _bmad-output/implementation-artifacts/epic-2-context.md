# Epic 2 Context: Pipeline Czytelnik — Fetch, Clean i Budowa EPUB (z podglądem)

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Deliver reader-first end-to-end where system politely fetches only chosen chapters with cache/resume, isolates body via per-adapter selectors + heuristic fallback correctable in preview, applies user filters once at EPUB build, and assembles a validated EPUB (title/author/cover/TOC, epubcheck clean) — so discovery from Epic 1 leads directly to a readable artifact with basic queue/log feedback.

## Stories

- Story 2.1: Polite Fetcher + cache + adaptive 429 + resume
- Story 2.2: Content boundary — selektory per-adapter + heuristic + preview korygowalny
- Story 2.3: Filtry — plain+regex na etapie EPUB build
- Story 2.4: EPUB Assembly + Result card + epubcheck

## Requirements & Constraints

- Polite fetch must be sequential 3–5s + jitter default, 10s safe mode, adaptive backoff on 429 with jitter and exponential retry cap 20s, no parallel scrape (NFR1). Cache owned by Core at `_cache/<sha1(normalized_url)>/raw.html` (sha1 owned by `core/fetch.py` AD-9), raw never filtered, resume badge `skipped N, fetching X–Y` via diff desired vs cache.
- Bounded range `20–100` re-run fetches only missing via cache diff; open-ended `to-end` re-validates `listChapters` for new chapters then fetches missing (NFR3). Progress derived by Core, GUI only renders.
- Content boundary must use per-adapter `start/end` selectors as source of truth (`adapters/novelphoenix.py getSelectors`), heuristic `article/div.chapter-content` only fallback never auto-overwrites adapter selectors (AD-7). Preview split 40/60 Original/Cleaned tabs shows diff, editable mono inputs live re-parse, Reset do adaptera restores; override stored as `adapters/overrides/<site>.json`.
- Filters plain `contains` + regex applied once at EPUB build on cleaned text after selector isolation; raw cache stays unfiltered invariant (`raw contains phrase while EPUB does not`) (AD-2). Filters persist in `store.json` `filters[]` via `tauri-plugin-store` AD-10, GUI writes on blur.
- EPUB must be `epubcheck` clean, 0 subscription-nag lines on 20-chapter sample, name `<slug>_chapters_<from>_to_<to>.epub`, cover/TOC correct; TTS later reads this EPUB via `extract_chapters` (AD-8). Single desktop bundle per OS, zero data leaves device after fetch (NFR5).
- Performance: 100-chapter polite scrape without ban, title search <5s per site parallel already, EPUB build offline.

## Technical Decisions

- Modular Pipes-and-Filters + Ports & Adapters (hexagonal) — `GUI → Core → Pipeline` and `Core → Port → Adapter` (AD-1), enforced via `core/ports.py ScraperPort` + import linter (`core-no-adapters`, `adapters-no-pipeline`). `core/fetch.py` owns politeness + cache key, `core/clean.py` selector isolation, `core/epub.py` EPUB assembly + filter gate + epubcheck.
- Filtering stage fixed at EPUB build (AD-2), raw HTML cached utf-8, cleaned filtered once. TTS chunk `3500` at sentence boundary ratified from `speak.py:split_text_for_tts`.
- Politeness ownership in `core/fetch.py` (AD-3) — delay tiers 3–5s jitter / 10s safe, `throttleChanged` event, Core decides tier. No parallel scrape.
- Core owns chapter list + cache + selection + EPUB manifest; Adapters own selectors + heuristic fallback (AD-5). Event bus single typed `chapterStatus/partStatus/logLine/throttleChanged/done` via Tauri emit/listen no polling (AD-6). EPUB as intermediate invariant feeding TTS `extract_chapters→split_text_for_tts→PartJob` (AD-8).
- Resume semantics AD-9: bounded diff vs cache, open-ended re-validate list. Config persistence AD-10 single `store.json` mirrors CLI flags (`voice rate parallel 2-3 chunk-size 3500 retries 5 scrapeDelay safeMode keep* filters[]`).

## UX & Interaction Patterns

- Chapter List already from Epic 1: range bar `od–do` + `Zaznacz/Odznacz` sync, `Wybrano N` clamp, virtualized >500, double-click eye opens preview placeholder — now wired to real preview in 2.2.
- Preview split 40/60 with tabs Original/Cleaned, editable `start/end` CSS selector inputs mono `JetBrains 12`, live re-parse diff, filter chips plain/regex badge + `x`, `Reset do adaptera` — per DESIGN Preview tabs + EXPERIENCE Preview split.
- Queue/Progress minimal for this epic: per-chapter row `queued/fetching/cleaning/done/error` + mini progress `progress-track`, expand not yet; log pane `role=log aria-live` mono, global elapsed + throttle badge `polite/safe`, resume badge `pominięto N`. Keep switches not yet (Epic 4).
- Result Output card for EPUB: path mono, size, epubcheck badge, `Open folder` via Tauri opener, `keepEPUB` reflection; FFmpeg missing warning not needed for EPUB (only TTS).
- States: polite fetching spinner, 429 throttled toast warning, ban error row + resume hint, empty preview `Nie wyizolowano`, offline-after-fetch handling (fetch needs net, build offline).
- Keyboard/a11y: same Find→table→CTA arrows roving, Space toggle, Ctrl+A, Esc modal trap, pills text+color+icon, AA focus rings `ring 2px`.

## Cross-Story Dependencies

- Story 2.1 is foundation gate — polite fetcher + sha1 cache + adaptive 429 must land before any fetch; 2.2/2.3/2.4 all depend on its `core/fetch.py` and `_cache` contract.
- Story 2.2 implements selector isolation + heuristic + preview override store `adapters/overrides/<site>.json`; consumed by 2.3 filters (need cleaned text) and 2.4 EPUB build (needs isolated body).
- Story 2.3 applies filters once at EPUB gate; depends on 2.2 cleaned text, and 2.4 consumes its filtered output. Raw invariant (raw contains nag, EPUB does not) must hold.
- Story 2.4 assembles EPUB via `core/epub.py` + `epubcheck` gate + Result card; depends on 2.1 fetched HTML + 2.2 isolation + 2.3 filters; produces artifact that Epic 3 `core/tts.py` will later consume via `extract_chapters`.
- Epic 2 is reader-first end-to-end (FR1-2 from Epic 1 → EPUB) with basic Queue/log; full live queue, keep switches, Settings/Filters full UI are deferred to Epic 4. Epic 3 audio builds on this EPUB.
