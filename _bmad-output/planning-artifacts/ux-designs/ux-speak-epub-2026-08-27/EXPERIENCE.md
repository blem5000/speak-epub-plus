---
name: Speak EPUB
status: final
sources:
  - _bmad-output/planning-artifacts/briefs/brief-speak-epub-2026-08-27/brief.md
  - _bmad-output/planning-artifacts/briefs/brief-speak-epub-2026-08-27/addendum.md
updated: 2026-08-27
---

# Speak EPUB — Experience Spine

> Desktop Tauri + Python sidecar. Reader-first, audiobook-second. Fast-path draft with [ASSUMPTION] tags where user deferred to trends.

## Foundation

**Form-factor:** single-surface desktop (Tauri WebView, Win/macOS/Linux). Primary entry: Windows double-click \Run-SpeakEPUB-Tauri.cmd\ → native window \1024x720 min, 1200x800 default\ [ASSUMPTION], centered column \max 960px\, preview widens to \1120px\. No mobile surface in v1.

**UI system:** Tailwind + shadcn/ui pattern (no locked dep yet, but spine assumes \{DESIGN.md}\ tokens). \DESIGN.md\ is visual identity; this spine is behavior. Tokens referenced as \{colors.primary}\, \{typography.body}\ etc. Inherit shadcn keyboard/aria defaults.

**App model:** local-first, no auth, no cloud. Python core is sidecar (\python -m speak\ or binary) via Tauri IPC; GUI never invents scraping/TTS — delegates to \speak.py:extract_chapters\, \split_text_for_tts\, \PartJob\ queue. Persistence: local config JSON for Settings/Filters (voice, rate, parallel, chunk-size, retries, delay, keeps).

## Information Architecture

| Surface | Reached from | Purpose |
|---|---|---|
| **Find** | App open (default) | Paste novel URL or type title → Search → results table \site | title match | chapters | link\ → Pick |
| **Chapter List** | Pick / paste direct chapter-list URL | Chapter list fetch (polite) with \from–to\ + checkboxes, total count, cover/title metadata preview |
| **Preview** | Chapters → Preview toggle / per-chapter eye | Content-boundary isolation (per-adapter selectors + heuristic fallback) in split view: Original vs Cleaned, editable selectors, filter chips inline |
| **Queue / Progress** | Start fetch/build | Live per-chapter & per-part queue: queued/fetching/cleaning/TTS/merging/done/error, logs pane, resume badge (\skipped N, fetching X–Y\) |
| **Result** | Queue done | Output cards: EPUB (keep toggle), per-chapter MP3, M4B/M4A with markers; \\Open folder\\, \\Play\\ [ASSUMPTION], path mono |
| **Settings** | Gear / menu | Persisted controls: voice Select, rate Slider, parallel 2-3, chunk-size, retries, scrape delay (3-5s+jitter / 10s safe), keep switches (EPUB/MP3/M4B) |
| **Filters** | Settings → Filters or Preview → Manage | User-defined strip phrases: plain contains + regex table, add/edit/delete, preview impact on EPUB stage |

Secondary nav is menu/gear only; no sidebar in v1 to keep first screen minimal. Settings/Filters open as Tauri modal windows, not nested dialogs >1 deep.

Composition reference: `mockups/find.html` (Find — hero input + results), `mockups/chapter-preview.html` (40/60 split + Range bar), `mockups/queue.html` (per-chapter & per-part progress + log). Spine wins on conflict over any mock — stated once here.

## Voice and Tone

Microcopy — brand voice lives in \DESIGN.md: Brand & Style\.

| Do | Don't |
|---|---|
| „Wklej link do powieści lub wpisz tytuł” | „Witaj! Wklej tutaj swój ulubiony tytuł! ✨” |
| „Znaleziono 142 rozdziały — wybierz zakres” | „Mamy dla Ciebie 142 rozdziały!” |
| „Pobieranie 35–40 • pominięto 34 (resume)” | „Pobieranie w toku...” |
| „Usunięto 2 wiersze subskrypcji” | „Błąd: wykryto niechciane treści” |
| „Budowanie M4B — scalanie partów 2/5” | „Tworzenie audiobooka... proszę czekać” |

Language v1: English primary [ASSUMPTION] — „Paste novel URL or title”, „Build EPUB”, „Keep EPUB / MP3 / M4B”. PL copy uses same brevity, verbs first. Numbers always explicit.

## Component Patterns

Behavioral; visual specs in \DESIGN.md: Components\.

| Component | Use | Behavioral rules |
|---|---|---|
| **Find input** | Find | Single Input \height 44px\ accepts URL or title. On type (title) debounced aggregator <5s; on paste URL fallback adapter guessing. Enter or „Szukaj” fires. Results table below, no page nav. Visual: \{colors.input\} + \{colors.ring\} focus, clear button. |
| **Results table** | Find | Columns: site \| title \| chapters \| link (truncated). Hover reveals „Wybierz” (\{colors.accent}\ left border on select). Entire row clickable, keyboard arrows + Enter. Visual: \{colors.muted\} hover, accent left border 2px on selected (see DESIGN.md Components / Search result row). |
| **Range bar** | Chapter List | Two number inputs \od–do\ + „Zaznacz zakres” + „Odznacz”. Syncs checkboxes; clamps to 1..N. Shows „Wybrano 6 z 142”. Visual: \DESIGN.md: Components / Range bar — \{colors.accent\} fill for active range track, \{rounded.full\} pills. |
| **Chapter table** | Chapter List | Checkbox per row, mono index, title. Bulk select via Shift. Virtualized if >500 rows [ASSUMPTION]. Sticky header. Double-click opens Preview for that chapter. Visual: \{colors.muted\} hover, accent left border on selected range. |
| **Preview split** | Preview | Left: chapter list (narrow). Right: tabs Original / Cleaned + selector inputs (start/end CSS) editable with live re-parse. Filter chips show what was stripped per chapter. „Reset do adaptera” reverts. |
| **Queue list** | Queue | Per-chapter row: status pill + mini progress + expand to parts (\_parts/*.mp3\ dots). Global header: elapsed, throttle indicator (polite/safe), pause/cancel (pause defers to v2 [ASSUMPTION]). Auto-scroll to live row. |
| **Output cards** | Result | Three cards: EPUB (always if keep), MP3 folder, M4B. Each shows path mono, size, chapter markers count. „Otwórz folder” uses Tauri opener. |
| **Settings form** | Settings | Grouped sections: Audio (voice, rate), Performance (parallel, chunk-size, retries), Scrape (delay preset + custom), Outputs (keeps). Slider + numeric pairing for rate. Persist on blur, no save button. |
| **Filters table** | Filters | Columns: type badge (plain/regex) \| phrase \| scope \| delete. Add via Input + type toggle. Live count „Usuwa średnio 2 linie/rozdz.”. Apply preview before build. |

## State Patterns

| State | Surface | Treatment |
|---|---|---|
| **Cold launch** | Find | Skeleton for input only? Actually input ready immediately; no loader. Focus in input. |
| **Searching titles** | Find | Input spinner right, table shows skeleton rows (3) matching columns, subtext „Przeszukuję NovelPhoenix + inne...”. Resolves <5s. |
| **No results** | Find | \{typography.display-sm}\: „Brak wyników dla „X”.” Below: „Spróbuj wkleić pełny URL” + link to fallback guessing. One CTA: „Wklej URL”. |
| **Chapter list loading** | Chapter List | Table skeleton 6 rows, header pulsing, text „Pobieram listę rozdziałów (polite)...”. |
| **Fetch 429 / throttled** | Queue | Toast warning \{colors.warning}\: „Zwolnienie — 429, zwiększam opóźnienie do 10s (safe)”. Adaptive delay badge updates. Retry countdown visible. Continues, not fatal. |
| **Ban / repeated 429** | Queue | Error state row: „Przerwa — wykryto ograniczenie. Wznów później.” Keep cache, show resume hint. No auto-retry flood. |
| **Empty preview (selector miss)** | Preview | Empty state: „Nie wyizolowano treści — popraw selektory lub zaznacz ręcznie.” Show heurisitic fallback button. |
| **Offline after fetch** | Any | No network needed after fetch — editing/preview/build local. If offline during fetch, row error + toast. |
| **Build done** | Result | Success card with check, confetti subtle? No — just \{colors.success}\ pill „Gotowe”. Subtext with epubcheck clean badge. |
| **Settings persisted** | Settings | Toast once „Zapisano” on blur, no blocking. Filters persist similarly. |
| **FFmpeg missing** | Queue/Result | Warning: „FFmpeg nie znaleziono — części pozostaną niescalone, M4B pominięte. \ffmpeg -version\” with path hint. |
| **Permission denied** | N/A | Local-only app, no auth — surface hidden concept not applicable, deliberately omitted. |

## Interaction Primitives

- **Keyboard:** \Tab\ cycles Find→table→primary CTA. \Enter\ confirms pick/range/start. Arrows navigate tables, \Space\ toggles checkbox, \Ctrl+A\ selects all chapters, \Esc\ closes modal. Preview selector inputs support \Ctrl+Z\.
- **Mouse:** click row to select, checkbox for multi, double-click to preview. Hover reveals per-row eye icon.
- **Banned:** drag-to-reorder chapters (order is spine order), infinite scroll in tables (virtualized scroll instead), hover-only affordances on primary CTA.
- **Progressive disclosure:** first screen shows only Input + Pick + range + Start. Voice/parallel/chunk-size/filters never on main flow — behind Settings gear.

## Accessibility Floor

Behavioral; visual contrast in \DESIGN.md: Colors\.

- WCAG 2.2 AA target for hobby tier: focus rings \{colors.ring}\ 2px AA vs background, keyboard operable tables (roving tabindex), \ria-live\ on queue status.
- Screen reader announces surface on nav: „Wyszukiwanie, wklej URL lub tytuł” / „Lista rozdziałów, 142 pozycje, wybrano 6” / „Kolejka, rozdział 5 z 10, część 2 z 3”.
- All status pills have text + color + icon (not color alone).
- \Esc\ always closes topmost modal (Settings/Filters). Focus trap inside modals.
- Log pane has \ole=log\ and \ria-live=polite\ for incremental lines.
- No motion beyond progress fill; respects \prefers-reduced-motion\.

## Key Flows

### 1. Marta — reader-first, builds clean EPUB only

Marta, 29, czyta na Kindle, ma 45-min przerwę. Chce 30 rozdziałów „Lord of Mysteries” bez noszenia laptopa z otwartymi kartami.

1. Otwiera Speak EPUB (double-click). Kursor już w polu „Wklej link...”. Wkleja tytuł „Lord of Mysteries”, Enter.
2. Widzi tabelę: NovelPhoenix 142 rozdz., inny site 138 — wybiera NovelPhoenix (więcej).
3. Lista rozdziałów ładuje się (polite spinner). Wpisuje \1–30\ w range bar, checkboxy zaznaczają się, widzi „Wybrano 30”.
4. Klika „Podgląd” przy rozdz. 5 — widzi Original pełne śmieci (nav/footer + 2 linie „Subscribe”), Cleaned już czyste; zostawia jak jest.
5. Klika „Buduj EPUB” (primary ink). Kolejka leci: fetching 1..30 z opóźnieniem 3–5s, log cicho tyka, pasek rośnie. Jeśli 429 → toast „Zwolnienie — przełączam na safe 10s”, kontynuuje; jeśli ban → wiersz „Przerwa — wykryto ograniczenie. Wznów później”, cache zachowany, resume podpowiada „pominięto 12, fetching 13–30”.
6. **Climax:** karta EPUB pojawia się — „Gotowe — lord_of_mysteries_chapters_001_to_030.epub (epubcheck ✓)”. Klika „Otwórz folder”, wysyła na Kindle. Zero audio, zero komplikacji — cel reader-first spełniony w 10 min tła.

### 2. Jan — listener, wants filtered M4B with chapter markers

Jan, 34, dojeżdża 1h dziennie, chce M4B z markerami i bez nagów subskrypcji czytanych na głos.

1. Wkleja URL NovelPhoenix bezpośrednio → adapter zgaduje, lista od razu.
2. Zaznacza rozdz. 40–50 checkboxes, przełącza keep: \EPUB ✓ / MP3 ☐ / M4B ✓\.
3. Otwiera Filters, dodaje regex \subscribe.*patreon\ i plain \Unlimited access\. Podgląd pokazuje „Usunięto 2 linie” w rozdz. 44.
4. Start — polite fetch 40–50, potem TTS queue: PartJob chunk \max 3500\, parallel 3, logs „retry 1/4...” obsługiwane automatycznie.
5. Patrzy na Queue: per-chapter expand widzi \_parts/part_01.mp3 ✔\, scalanie via FFmpeg.
6. **Climax:** M4B z markerami gotowy — karta „book_chapters_040_to_050.m4b • 11 markerów • 1h 42m” + „Play”. Wznawia jutro dla 51–60, app pomija istniejące (_parts skipped).

## Responsive & Platform

| Breakpoint | Behavior |
|---|---|
| \≥1200px\ default | Centered 960px, Preview widened 1120px, table comfortable, Settings modal 560px centered. |
| \900–1199px\ narrow desktop | Column still centered, Preview stacks to single col with tabs, table density unchanged. |
| \<900px\ | Not supported as window minimum is 900px [ASSUMPTION]; no mobile layout in v1. |

Tauri: drag region on title bar, native open-folder, native notifications for done/error (opt-in). No auto-update in v1.

## Inspiration & Anti-patterns

**Inspiration:** Calibre (progressive disclosure), shadcn/docs (neutral minimal), Pocket (clean read view).

**Anti-patterns:** scraping tools with aggressive parallel + no jitter (ban), online converters requiring upload, EPUB readers that read chrome aloud, audio tools with truncated TTS (>3500 chars) — avoid by keeping chunk-size visible in Settings with helper „obniż jeśli słyszysz ucięcia”.

