---
stepsCompleted: [step-01, step-02, step-03, step-04]
inputDocuments:
  - _bmad-output/specs/spec-speak-epub/SPEC.md
  - _bmad-output/planning-artifacts/architecture/architecture-speak-epub-2026-08-27/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/ux-designs/ux-speak-epub-2026-08-27/DESIGN.md
  - _bmad-output/planning-artifacts/ux-designs/ux-speak-epub-2026-08-27/EXPERIENCE.md
---

# speak epub - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for speak epub, decomposing the requirements from the PRD, UX Design if it exists, and Architecture requirements into implementable stories.

## Requirements Inventory

### Functional Requirements

FR1: Reader can find a novel by pasting its URL or typing its title and seeing per-site matches with chapter counts to pick the source (CAP-1).
FR2: Reader can fetch the chapter list politely and pick an exact range via from-to inputs plus checkboxes with total count visible (CAP-2).
FR3: System can fetch only the chosen chapters politely with cache and resume and isolate body via per-adapter start/end CSS selectors plus heuristic fallback with preview-correctable bounds and strip user-defined filter phrases (CAP-3).
FR4: System can assemble a validated EPUB (title, author, cover if available, TOC) as a standalone artifact with filter phrases applied once at build (CAP-4).
FR5: System can turn the built EPUB into per-chapter MP3s and a single M4B/M4A with chapter markers using sentence-boundary chunking and a global parallel queue (CAP-5).
FR6: Reader can see live per-chapter and per-part progress with logs and throttle tier and persist all settings across restarts to control outputs (CAP-6).

### NonFunctional Requirements

NFR1: Politeness & rate-limiting — sequential fetch only with 3–5s + jitter default and 10s safe mode, adaptive backoff on 429 with jitter and exponential retry cap 20s; no parallel scrape even though TTS runs parallel 2–3 (SPEC Constraints).
NFR2: Performance — title search per site in <5s parallel, 100-chapter polite scrape without ban, 10-chapter M4B build in <1h on parallel 3 (SPEC Success signal).
NFR3: Reliability & resume — bounded range fetches only missing via sha1(url) cache diff, open-ended re-validates list for new chapters; PartJob 5 retries with backoff min(20, 2*attempt); raw HTML cached, resume badge skipped N correctly.
NFR4: Quality gate — EPUB must be epubcheck clean with 0 subscription-nag lines on 20-chapter sample, cover/TOC correct; TTS chunk max_chars 3500 at sentence boundaries, no truncation.
NFR5: Local-first & offline — zero data leaves device after fetch; preview, EPUB build, and audio work offline after fetch; single desktop artifact for Win/macOS/Linux via Tauri with Windows double-click shortcut.
NFR6: Compatibility & brownfield — Python 3.10+, venv at Speak-EPUB-1.0.0/venv (Scripts/python.exe Win vs bin/python macOS/Linux via core/config.py), FFmpeg/ffprobe required via shutil.which, reuse existing PartJob frozen dataclass and spine-order numbering.
NFR7: Licensing & extensibility — MIT, community adapter model, Ports & Adapters (ScraperPort) so new site added without touching Core.

### Additional Requirements

- Starter/template: Tauri 2.11.5 (verified 2026-07-01, api 2.11.1, cli 2.11.4), create-tauri-app 4.7.3 [ASSUMPTION deferred to cargo add], Frontend React 18 + TypeScript 5 + Vite 6 + Tailwind 4 + shadcn/ui [ASSUMPTION] — impacts Epic 1 Story 1 project scaffold.
- Infrastructure: single desktop bundle per OS via tauri-bundler; no server; FFmpeg bundled or PATH-checked; local JSON store via tauri-plugin-store for config persistence.
- Integration: Python sidecar Speak-EPUB-1.0.0/venv via tauri-plugin-shell, JSON-RPC stdin/stdout primary with HTTP fallback after 10-min spike; core/config.py OS-aware venv path; dependency direction GUI -> Core -> Pipeline + Port -> Adapter (AD-1).
- Data: chapter id = spine order 1..N, PartJob frozen, cache at _cache/<hash>/raw.html keyed by sha1(normalized_url) owned by Core (AD-9), raw never filtered, cleaned filtered at EPUB gate (AD-2).
- API contract: ScraperPort ABC with search(title), listChapters(url), fetchChapter(url), getSelectors(); event bus chapterStatus/partStatus/logLine/throttleChanged/done, no polling (AD-6); EPUB is only TTS source (AD-8).
- Security: no auth in v1, cookie/header port hidden behind experimental flag; no secrets in store.
- Monitoring/logging: logs role=log via event bus to GUI log pane with aria-live; progress derived by Core.

### UX Design Requirements

UX-DR1: Implement design token system from DESIGN.md frontmatter — colors (background/foreground/muted/border/input/ring/primary/accent/success/warning/destructive with dark pairs, hex) and typography (display 28/20, heading 16, body 14/13, mono JetBrains Mono 12) and rounded (sm 6/mb 8/lg 12/xl 16/full) and spacing (xs 4 .. 2xl 48) — expose as CSS vars / Tailwind config.
UX-DR2: Build reusable component Find input (44px, clear+paste, focus ring {colors.ring}) with debounced aggregator and results table (site|title|chapters|link, hover muted, selected accent left border + #EFF3FF) — per DESIGN Components + EXPERIENCE Find input/Results table.
UX-DR3: Build Chapter List surface — Range bar (od–do inputs + Zaznacz/ Odznacz, syncs checkboxes, shows Wybrano N) + virtualized Chapter table (checkbox, mono index, 36px rows, zebra muted hover, sticky header, accent highlight for selected range, double-click opens Preview).
UX-DR4: Build Preview split (40/60) with tabs Original/Cleaned, editable start/end CSS selector inputs (mono) with live re-parse, filter chips (plain/regex badge + text + x), Reset do adaptera — per DESIGN Preview tabs + EXPERIENCE Preview split.
UX-DR5: Build Queue/Progress list — per-chapter row (status pill queued/fetching/cleaning/TTS/merging/done/error + mini progress {components.progress-track}, expand to parts _parts/*.mp3 dots, auto-scroll to live), global header elapsed + throttle badge (polite/safe), plus log pane (mono, role=log, aria-live) and resume badge.
UX-DR6: Build Result Output cards (EPUB/MP3/M4B) with path mono, size, chapter markers count, Open folder (Tauri opener) and Play, epubcheck badge, keep switches reflection.
UX-DR7: Build Settings form (grouped Audio: voice Select + rate Slider, Performance: parallel 2-3 / chunk-size 3500 / retries 5, Scrape: delay preset + custom + safeMode, Outputs: keepEPUB/MP3/M4B) and Filters table (type badge plain/regex, phrase, scope, delete, add via Input + toggle, live avg lines removed) — persisting on blur, no save button.
UX-DR8: Implement state treatments per EXPERIENCE State Patterns — cold launch focus in input, searching skeleton rows, no results empty state (display-sm + Wklej URL CTA), chapter list loading skeleton, 429 throttled toast (warning), ban error row + resume hint, empty preview, offline-after-fetch handling, build done success pill, FFmpeg missing warning.
UX-DR9: Implement interaction primitives — keyboard: Tab cycles Find→table→CTA, Enter confirms, arrows navigate tables, Space toggles checkbox, Ctrl+A select all, Esc closes modal, Ctrl+Z in selector inputs; mouse: row click/select, double-click preview, hover eye; ban drag-to-reorder and infinite scroll; enforce progressive disclosure (first screen only input+pick+range+Start, advanced behind gear).
UX-DR10: Meet accessibility floor — WCAG 2.2 AA (focus rings {colors.ring} 2px, AA contrast), keyboard operable tables (roving tabindex), aria-live on queue, screen-reader announces surface on nav (Wyszukiwanie / Lista 142 / Kolejka 5/10), status pills with text+color+icon, Esc closes modal with focus trap, respects prefers-reduced-motion.
UX-DR11: Handle responsive & platform — centered max 960px (content) / 1120px preview, narrow 900–1199 single-col Preview, window min 900px (no mobile v1), Tauri drag region, native open-folder, opt-in native notifications, no auto-update in v1.

### FR Coverage Map
FR1: Epic 1 — Find (URL/title → site|chapters|link)
FR2: Epic 1 — Choose (lista + od–do + checkboxes)
FR3: Epic 2 — Fetch & Clean (polite + cache + selektory + preview + filtry)
FR4: Epic 2 — Build EPUB (valid, filtry raz, cover/TOC)
FR5: Epic 3 — Make Audio (chunk 3500 + PartJob + M4B markers)
FR6: Epic 4 — Control & Persist (live queue + Settings/Filters + resume + persist)

## Epic List

### Epic 1: Discovery — Znajdź i Wybierz (agregator + lista)
Po tym epiku użytkownik może wkleić URL/tytuł, zobaczyć counts per site (agregator), wybrać źródło i zakres od–do z checkboxami — discovery działa standalone z mock fetch (bez prawdziwego pobierania), z GUI Find + Chapter List gotowym do demo.
**FRs covered:** FR1, FR2

### Epic 2: Pipeline Czytelnik — Fetch, Clean i Budowa EPUB (z podglądem)
Po tym epiku system pobiera grzecznie tylko wybrane rozdziały z cache/resume, izoluje treść via selektory + heuristic + preview-correct, nakłada filtry raz na buildzie i składa zwalidowany EPUB (epubcheck, 0 nag) — reader-first end-to-end (FR1-2 → EPUB) z podstawowym Queue/log i Result.
**FRs covered:** FR3, FR4

### Epic 3: Słuchacz M4B — z EPUB do audiobooka z markerami
Po tym epiku użytkownik może z istniejącego EPUB zbudować per-chapter MP3 i jeden M4B/M4A z markerami, z chunkingiem 3500, globalną kolejką PartJob parallel 2–3 i merge FFmpeg — audiobook-second standalone na bazie Epiku 2.
**FRs covered:** FR5

### Epic 4: Desktopowa Kontrola — pełny live, persist i poler UX
Po tym epiku użytkownik dostaje pełny Tauri GUI: rozbudowany live queue per chapter+part z logami i badge throttle, keep-switches, pełne Settings/Filters (voice/rate/parallel/chunk/retries/delay/keeps, plain+regex), resume conditional (bounded missing-only vs open-ended re-validate), a11y AA i responsive — komfort i persist across restarts.
**FRs covered:** FR6




## Epic 1: Discovery — Znajdź i Wybierz (agregator + lista)

Reader może wkleić URL/tytuł, zobaczyć counts per site (agregator), wybrać źródło i zakres od–do z checkboxami — discovery działa standalone z mock fetch (bez prawdziwego pobierania treści), z GUI Find + Chapter List gotowym do demo.
**FRs covered:** FR1, FR2

### Story 1.1: Scaffold Tauri + Python sidecar + ScraperPort + tokeny

As a developer,
I want scaffold Tauri 2.11.5 + Python sidecar contract + ScraperPort ABC + design tokens + OS-aware venv path,
So that reszta epików ma stabilny kontrakt i nie dotyka plików ponownie.

**Acceptance Criteria:**

**Given** czysty repo bez src-tauri/ i Speak-EPUB-1.0.0/core/, **When** create-tauri-app 4.7.3 z React 18/TS5/Vite6/Tailwind4/shadcn zainicjuje projekt i tauri-plugin-shell/store dodane, **Then** npm run tauri dev startuje okno 960px z DESIGN.md tokens (colors/typography/rounded/spacing) jako CSS vars i auto-detect locale (en/pl) działa.
**Given** core/ports.py z ScraperPort.search/listChapters/fetchChapter/getSelectors, **When** adapters/novelphoenix.py implementuje ABC, **Then** import linter blokuje core→adapters.* direct i adapters→core.pipeline.
**Given** sidecar venv path, **When** core/config.py wykrywa OS, **Then** Scripts/python.exe na Win i bin/python na macOS/Linux via tauri-plugin-shell + JSON-RPC stdin/stdout (spike 10 min zaliczony), fallback HTTP udokumentowany.

### Story 1.2: Adapter NovelPhoenix — search + listChapters + cover/metadata

As a reader,
I want adapter, który znajduje po tytule i pobiera listę rozdziałów z coverem,
So that mogę wybrać źródło bez ręcznego wklejania każdego linku.

**Acceptance Criteria:**

**Given** tytuł „Lord of Mysteries”, **When** search(title) woła NovelPhoenix, **Then** zwraca site|title|chapters|link z poprawnym chapters count w <5s i fallback guessing dla nieznanej domeny wybiera heurystykę.
**Given** URL listy rozdziałów, **When** listChapters(url) polite fetch (sequential), **Then** zwraca ordered 1..N z tytułami, cover URL jeśli jest, pomija empty, spine order zachowany i test selectorów zielony.

### Story 1.3: Powierzchnia Find — input + agregator + tabela wyników

As a reader,
I want wpisać URL/tytuł i zobaczyć tabelę site|chapters|link,
So that wybieram źródło одним kliknięciem.

**Acceptance Criteria:**

**Given** Find focused, **When** wpisuję tytuł (debounced), **Then** skeleton rows 3 + „Przeszukuję NovelPhoenix + inne…”, po <5s tabela z hover muted i selected accent left border + #EFF3FF, cały wiersz klikalny, Enter wybiera.
**Given** no results, **When** search kończy pusto, **Then** display-sm „Brak wyników dla ‘X’” + CTA „Wklej URL” + link fallback.
**Given** tabela, **When** Tab→arrows→Enter/Space, **Then** roving tabindex, Enter = Wybierz, focus ring {colors.ring} 2px AA.

### Story 1.4: Powierzchnia Chapter List — from–to + checkboxes

As a reader,
I want wybrać zakres od–do i checkboxy,
So that wskazuję co pobrać bez klikania setek checkboxów.

**Acceptance Criteria:**

**Given** lista 142 załadowana (skeleton 6 rows podczas load), **When** wpisuję 1–30 w Range bar i klikam Zaznacz, **Then** 30 checkboxów zaznaczonych, label „Wybrano 30 z 142”, clamp 1..N, Shift bulk select działa, virtualized jeśli >500.
**Given** tabela, **When** double-click row, **Then** otwiera Preview placeholder (pełny preview w Epic2), row hover eye widoczny.
**Given** wybór, **When** Tab/Enter/Space/Ctrl+A, **Then** pełna obsługa klawiatury, Esc nie zamyka listy, stan zapisany w Core (nie GUI) na następny epic.

## Epic 2: Pipeline Czytelnik — Fetch, Clean i Budowa EPUB (z podglądem)

System pobiera grzecznie tylko wybrane rozdziały z cache/resume, izoluje treść via selektory + heuristic + preview-correct, nakłada filtry raz na buildzie i składa zwalidowany EPUB (epubcheck, 0 nag) — reader-first end-to-end z podstawowym Queue/log i Result.

**FRs covered:** FR3, FR4

### Story 2.1: Polite Fetcher + cache + adaptive 429 + resume

As a system,
I want fetcher, który pobiera sequential 3-5s+jitter/10s safe z cache i adaptive backoff,
So that 100 rozdziałów nie banuje i resume działa.

**Acceptance Criteria:**

**Given** wybrany zakres 1-100, **When** fetcher startuje sequential, **Then** delay 3-5s + jitter default, raw HTML cachowany w _cache/<hash>/raw.html keyed by sha1(normalized_url) owned by Core, no parallel scrape.
**Given** HTTP 429, **When** fetcher dostaje 429, **Then** increment do safe 10s, jitter, exponential retry cap 20s, emit throttleChanged, GUI badge aktualizuje się, kontynuuje bez flood.
**Given** cache z 1-20 już istnieje, **When** bounded range 20-100 ponownie, **Then** diff vs cache fetch tylko missing (badge „pominięto 20, pobieram 21-100”); **When** open-ended to-end, **Then** re-validate listChapters wykrywa nowe i pobiera tylko nowe.

### Story 2.2: Content boundary — selektory per-adapter + heuristic + preview korygowalny

As a reader,
I want preview, który izoluje treść i pozwala poprawić selektory,
So that EPUB nie zawiera nav/footer gdy layout driftuje.

**Acceptance Criteria:**

**Given** adapter NovelPhoenix z start/end selektorami, **When** cleaner izoluje chapter, **Then** używa per-adapter selektorów; heuristic article/div.chapter-content tylko jako fallback i nigdy nie nadpisuje automatycznie selektorów adaptera.
**Given** Preview split 40/60, **When** otwieram rozdział, **Then** tabs Original/Cleaned pokazują diff, editable start/end inputs (mono) live re-parse, Reset do adaptera przywraca.
**Given** layout drift, **When** poprawiam selektor i zapisuję, **Then** override zapisany w adapters/overrides/<site>.json i użyty przy następnym fetch.

### Story 2.3: Filtry — plain+regex na etapie EPUB build

As a reader,
I want filtry plain contains + regex nakładane raz na buildzie EPUB,
So that audio też czyste i jedno źródło prawdy.

**Acceptance Criteria:**

**Given** filtry „Subscribe” (plain) i „subscribe.*patreon” (regex) w store.json, **When** epub.py składa EPUB, **Then** nakłada filtry raz na cleaned text po izolacji selektorów, raw cache nadal zawiera nag (test: raw contains filter phrase while EPUB text does not).
**Given** Filters UI, **When** dodaję/usuwam filtr (type badge + phrase + x), **Then** tabela w Settings/Filters aktualizuje się, live count „usuwa średnio 2 linie/rozdz.”, persist on blur, preview chip pokazuje ile usunięto per chapter.

### Story 2.4: EPUB Assembly + Result card + epubcheck

As a reader,
I want zwalidowany EPUB z cover/TOC i Result card,
So that wysyłam na czytnik bez ręcznego sprzątania.

**Acceptance Criteria:**

**Given** wybrane 20 rozdziałów z coverem, **When** epub.py buduje, **Then** EPUB ma title/author/cover/TOC correct, nazwa <slug>_chapters_<from>_to_<to>.epub, epubcheck clean na 20-chapter sample, 0 nag lines po filtrach.
**Given** EPUB gotowy, **When** Result card render, **Then** pokazuje path mono, size, epubcheck badge, Open folder via Tauri opener działa, keepEPUB switch respektowany, offline po fetch działa.
**Given** minimal Queue/log z Epic1, **When** fetch→clean→build leci, **Then** per-chapter status queued/fetching/cleaning/done + log pane role=log aria-live + resume badge działają (pełny TTS jeszcze nie).

## Epic 3: Słuchacz M4B — z EPUB do audiobooka z markerami

Użytkownik może z istniejącego EPUB zbudować per-chapter MP3 i jeden M4B/M4A z markerami, z chunkingiem 3500, globalną kolejką PartJob parallel 2–3 i merge FFmpeg — audiobook-second standalone na bazie Epiku 2.

**FRs covered:** FR5

### Story 3.1: TTS Chunking + PartJob queue (ratyfikacja brownfield)

As a system,
I want chunking sentence-boundary 3500 + PartJob global queue w reading order,
So that Edge TTS nie ucina i kolejka jest deterministyczna.

**Acceptance Criteria:**

**Given** rozdział >3500 chars, **When** split_text_for_tts dzieli, **Then** tnie na granicy zdań (?[.!?;:]) z fallback twardym cięciem jeśli zdanie >3500, wszystkie chunki ≤3500 i w kolejności.
**Given** EPUB z 3 rozdziałami (2,1,2 chunki), **When** buduję queue, **Then** PartJob frozen dataclass (chapter_number, part_number, part_count, text, output_path, is_final_chapter_file) w globalnej kolejce reading order: ch40 p1..20 najpierw, potem ch41 p1 itd.

### Story 3.2: Edge TTS + parallel 2–3 + retries + _parts skip

As a system,
I want Edge TTS parallel 2–3 + 5 retries + skip _parts na resume,
So that audio buduje się szybko i wznawia.

**Acceptance Criteria:**

**Given** queue 20 partów, **When** start z parallel 3, **Then** 1,2,3 startują first, po zakończeniu jednego startuje 4-ty, itd., z szacunkiem dla Edge throttling.
**Given** Edge 429/throttle, **When** tts_text_to_mp3 woła edge-tts 7.2.8, **Then** retry 5x backoff min(20,2*attempt) z log „retry 1/4 dla part_02.mp3”, po wyczerpaniu error; istniejące _parts/*.mp3 skip na re-run (resume).

### Story 3.3: FFmpeg merge per-chapter + single M4B z markerami

As a reader,
I want scalone per-chapter MP3 i jeden M4B z markerami,
So that słucham na telefonie z rozdziałami.

**Acceptance Criteria:**

**Given** _parts per chapter, **When** FFmpeg concat via concat.txt -c copy, **Then** per-chapter MP3 scalony w book order, jeśli FFmpeg brak → parts zostają niescalone i warning „ffmpeg -version” w logu.
**Given** per-chapter MP3 gotowe, **When** buduję M4B z chapter markers via FFmpeg chapter metadata, **Then** single <slug>_chapters_<from>_to_<to>.m4b z markerami i duration ms via ffprobe verified na Win, 10-chapter sample <1h, keep switches EPUB/MP3/M4B respektowane, Result M4B card pokazuje „11 markerów • 1h 42m” + Play/Open folder.

## Epic 4: Desktopowa Kontrola — pełny live, persist i poler UX

Użytkownik dostaje pełny Tauri GUI: rozbudowany live queue per chapter+part z logami i badge throttle, keep-switches, pełne Settings/Filters, resume conditional, a11y AA i responsive — komfort i persist across restarts.

**FRs covered:** FR6

### Story 4.1: Live Queue expansion + event bus + throttle/badge + log

As a reader,
I want live queue per chapter+part z logami i throttle badge,
So that widzę co się dzieje i mogę wznowić.

**Acceptance Criteria:**

**Given** fetch→TTS leci, **When** Core emit chapterStatus/partStatus/logLine/throttleChanged/done via Tauri, **Then** GUI renderuje per-chapter row (pill queued/fetching/cleaning/TTS/merging/done/error + mini progress {components.progress-track} + expand parts dots) + global elapsed + throttle polite/safe badge, no polling, auto-scroll do live row.
**Given** re-run z cache, **When** Core diff vs desired range, **Then** badge „pominięto N, pobieram X–Y” + log „skipped _parts/*.mp3” poprawny, queue pokazuje skipped jako done.

### Story 4.2: Settings form + persist store.json + i18n auto-detect

As a reader,
I want Settings, które persistują i auto-detect języka,
So that nie ustawiam co run.

**Acceptance Criteria:**

**Given** Settings gear, **When** otwieram, **Then** grupy Audio (voice Select), Performance (parallel 2-3, chunk 3500, retries 5), Scrape (delay 3-5s jitter + custom + safeMode), Outputs (keepEPUB/MP3/M4B) z helper typography.body-sm muted, Slider+number paired dla rate, persist on blur via tauri-plugin-store store.json mirror CLI flags, no save button, toast „Zapisano”.
**Given** system locale PL, **When** app start, **Then** t() keys z pl.json, fallback en.json, brak hardcode stringów — verified via i18n abstraction.

### Story 4.3: Filters window pełny + integracja z Preview + EPUB gate

As a reader,
I want Filters window + chips w Preview,
So that sprzątam nag raz a dobrze.

**Acceptance Criteria:**

**Given** Filters window, **When** dodaję plain „Unlimited access” i regex „subscribe.*patreon”, **Then** tabela type badge + phrase + x, live „usuwa średnio 2 linie/rozdz.”, persist on blur, dopisane do store.json filters[].
**Given** Preview, **When** filtr aktywny, **Then** chip pokazuje ile usunięto per chapter, raw cache nadal zawiera nag (invariant), cleaned w epub.py raz na buildzie po izolacji selektorów, Original vs Cleaned diff widoczny.

### Story 4.4: State treatments + a11y AA + responsive & platform

As a reader,
I want stany, a11y i responsywność dopracowane,
So that apka jest schludna i dostępna.

**Acceptance Criteria:**

**Given** Find cold launch, **When** otwieram app, **Then** focus w input, cold skeleton rows gdy searching, no results display-sm + Wklej URL CTA, chapter list loading skeleton 6 rows, 429 toast warning, ban error row + resume hint, empty preview „Nie wyizolowano”, FFmpeg missing warning z path hint.
**Given** WCAG AA, **When** Tab roving po tabelach, **Then** focus ring {colors.ring} 2px AA, aria-live na queue, screen reader „Wyszukiwanie…/Lista 142/Wybrano 6/Kolejka 5/10”, Esc zamyka modal z focus trap, respects prefers-reduced-motion, status pills text+color+icon.
**Given** breakpoints, **When** width 960 vs 1120 preview, **Then** centered 960, preview widened 1120, 900-1199 single-col Preview, window min 900, Tauri drag region + native open-folder via opener + opt-in native notifications, no auto-update.

