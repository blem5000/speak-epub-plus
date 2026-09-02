# Epic 1 Context: Discovery — Znajdź i Wybierz (agregator + lista)

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Deliver standalone discovery so a reader can paste a novel URL or type a title, see per-site matches with chapter counts, pick a source, and choose an exact chapter range via from-to inputs and checkboxes. This epic establishes the Tauri + Python sidecar contract, ScraperPort abstraction, design tokens, and the Find + Chapter List surfaces with mock fetch only — no real chapter-body download — making the flow demonstrable end-to-end for source selection before any pipeline work.

## Stories

- Story 1.1: Scaffold Tauri + Python sidecar + ScraperPort + tokeny
- Story 1.2: Adapter NovelPhoenix — search + listChapters + cover/metadata
- Story 1.3: Powierzchnia Find — input + agregator + tabela wyników
- Story 1.4: Powierzchnia Chapter List — from–to + checkboxes

## Requirements & Constraints

- Discovery must support two entry paths: direct novel URL and title search. Title search queries supported sites in parallel and shows per-site results with chapter count and link for source comparison; unknown-domain URLs use fallback heuristic guessing to select an adapter.
- Chapter list fetch must indicate politeness and return ordered titles numbered by spine order 1..N, skipping near-empty pages, preserving author/title/cover metadata when available.
- Range selection must sync bidirectional between from-to inputs and checkboxes, display total count and "Wybrano N z M", clamp to 1..N, support bulk Shift-select and Ctrl+A, and persist selection state in Core (not GUI view state).
- Performance target for title search is under 5 seconds per site when run in parallel; list fetch is sequential and polite. No parallel scrape is allowed even though later TTS will use parallelism.
- Empty and loading states are required: skeleton rows while searching/loading, distinct no-results state with URL-paste call-to-action, and double-click on a chapter row as the affordance to open preview (placeholder in this epic, full in Epic 2).
- Local-first desktop: single Tauri bundle per OS, Windows double-click launch, zero data leaves device after fetch; only chapter-list fetch needs network in this epic.
- Success is demonstrable with mock fetch — no epubcheck/M4B gate — but spine-order IDs and chapter-count accuracy must hold for Epic 2.

## Technical Decisions

- Paradigm is Modular Pipes-and-Filters plus Ports & Adapters (hexagonal at scrape boundary). Dependency direction is GUI (Tauri+React) -> Core orchestrator -> Pipeline and Core -> ScraperPort -> Adapter. Adapters import nothing from Core pipeline; pipeline never imports concrete adapters. Enforced via `core/ports.py` defining the `ScraperPort` ABC and an import linter.
- `ScraperPort` exposes `search(title)`, `listChapters(url)`, `fetchChapter(url)`, `getSelectors()`. First adapter is `adapters/novelphoenix.py`; future adapters plug without touching Core. Title aggregator in `core/aggregator.py` is a port consumer with parallel per-site fan-out.
- Tauri sidecar contract: Rust backend spawns Python via `tauri-plugin-shell` with JSON-RPC over stdin/stdout as primary transport and HTTP localhost fallback if the 10-minute spike fails. Python path is OS-aware via `core/config.py` — `Speak-EPUB-1.0.0/venv/Scripts/python.exe` on Windows vs `venv/bin/python` on macOS/Linux — never bare `python`.
- Core owns chapter list, cache key (`sha1(normalized_url)` in `core/fetch.py`), selection state, and progress. GUI is thin shell only. Chapter ID is spine order; naming `<slug>_chapters_<from>_to_<to>.epub/.m4b` fixed for later epics.
- Event bus is single typed channel: `chapterStatus`, `partStatus`, `logLine`, `throttleChanged`, `done` via Tauri emit/listen, no polling. Epic 1 uses only list-fetch status and logs.
- Config persistence is single local JSON via `tauri-plugin-store` (`store.json`) mirroring CLI flags (`voice`, `rate`, `parallel` 2-3, `chunk-size` 3500, `retries` 5, `scrapeDelay`, `safeMode`, `keep*`, `filters[]`). GUI writes on blur, Core reads on start.
- Stack for this epic: Tauri 2.11.5, create-tauri-app 4.7.3, React 18 + TS 5 + Vite 6 + Tailwind 4 + shadcn/ui, Python 3.10+ with `ebooklib`/`BeautifulSoup4`/`lxml`/`edge-tts`, FFmpeg via `shutil.which`. Seed is `core/`, `adapters/`, `adapters/overrides/`, `src-tauri/`.

## UX & Interaction Patterns

- Tokens are the visual contract: neutral bg/fg/muted/border/input plus single action blue and status colors, typography tiers (display 28/20, heading 16, body 14/13, mono JetBrains 12), rounding 6-16 and spacing 4-48 — exposed as CSS vars/Tailwind.
- Find: 44px input with clear+paste, 2px focus ring, debounced aggregator with spinner and 3-row skeleton; results table site | title | chapters | link with muted hover, selected accent left border 2px plus light bg; whole row clickable/keyboard-navigable.
- Chapter List: range bar od-do plus Zaznacz/Odznacz syncing checkboxes, "Wybrano N", clamp 1..N; 36px rows with mono index, zebra hover, sticky header, accent highlight for selected range, virtualized >500 rows; double-click eye opens preview placeholder.
- States: cold launch focuses Find input; searching shows skeleton; no results shows display-sm plus "Wklej URL" CTA; list loading shows 6-row skeleton with polite text.
- Disclosure: first screen only input+pick+range+Start; voice/parallel/chunk/rate/filters behind gear. No drag-to-reorder or infinite scroll.
- Keyboard/a11y: Tab Find->table->CTA; arrows with roving tabindex; Space toggles; Ctrl+A all; Enter confirms; Esc closes modal with focus trap; pills text+color+icon; log `role=log`/`aria-live`; announces "Wyszukiwanie / Lista 142 / Wybrano 6"; AA focus rings, respects `prefers-reduced-motion`.
- Layout: centered 960px (preview 1120px), 900-1199 stacks preview, window min 900px, no mobile v1; Tauri drag region and native opener; no auto-update.

## Cross-Story Dependencies

- Story 1.1 is the foundation gate — ScraperPort ABC, OS-aware venv path, sidecar IPC spike, and token/CSS-var setup must land before any adapter or surface work.
- Story 1.2 implements the port for NovelPhoenix (search, listChapters, cover) and defines selector ownership; it is consumed directly by the aggregator and list surfaces.
- Story 1.3 depends on 1.1 tokens/layout and 1.2 aggregator results to render the Find input and results table correctly.
- Story 1.4 depends on 1.2 for the ordered chapter list and on 1.1 for Core-owned selection state and tokenized table/range styling; it also establishes the double-click affordance that Epic 2 will wire to the real preview.
- Epic 1 is intentionally decoupled from Epics 2-4 — it validates discovery with mock fetch so Epic 2 (polite fetch/clean/EPUB with real cache and resume) and later audio/control epics can build on the same ScraperPort and state contracts without rework.
