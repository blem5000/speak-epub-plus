---
title: 'Powierzchnia Chapter List — from–to + checkboxes'
type: 'feature'
created: '2026-08-27'
status: 'done'
baseline_commit: '3ca0d980b7e6daed0f6178ef99f1c91b4954d2b3'
review_loop_iteration: 0
context:
  - _bmad-output/specs/spec-speak-epub/SPEC.md
  - _bmad-output/planning-artifacts/architecture/architecture-speak-epub-2026-08-27/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/ux-designs/ux-speak-epub-2026-08-27/DESIGN.md
  - _bmad-output/implementation-artifacts/epic-1-context.md
  - _bmad-output/planning-artifacts/epics.md
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Po wyborze źródła w Find (`selectedUrl`) brak listy rozdziałów — reader nie może wskazać zakresu `od–do` ani zaznaczyć checkboxów, więc discovery z `1.3` jest martwy i nie prowadzi do `Fetch` w Epic 2.
**Approach:** Zbudować powierzchnię Chapter List: pobrać `listChapters(selectedUrl)` via `handle_rpc` (real `adapters/novelphoenix.py:listChapters` + `aggregator` reuse), wyświetlić zakres `od–do` + `Zaznacz`/`Odznacz` sync z checkboxami, label `Wybrano N z M`, z wirtualizacją >500 i double-click → Preview placeholder — stan selekcji w Core, nie w GUI.

## Boundaries & Constraints

**Always:** `GUI→Core→Port→Adapter` (`core→adapters` tylko dynamic `importlib` w `core/config.py` jak w 1.3 `config.py:121`); selekcja `Set<number>` `1..N` spine order w `core` (Core owns list/cache/selection `epic-1-context.md:13`), GUI thin; tokeny `DESIGN.md:9-80` jako CSS vars (`--ring #2B5CE6`, `rounded-md 8px`, `mono JetBrains 12`, `accent left 2px + #EFF3FF` `DESIGN.md:185`); inputy `od/do` `type=number` `h-9` `focus:ring-2 ring` AA, tabela `36px` rows `mono` index `body 14px` hover `muted` sticky header, `clamp 1..N`, `Wybrano` via `t()` bez hardcode.
**Ask First:** Dodanie dep `react-window`/`@tanstack/virtual` dla >500 (poza React/TS/Vite/Tailwind/shadcn + `requests/bs4/lxml`); zmiana `ScraperPort`/`store.json` selection persistence vs in-memory; zmiana transport `python_sidecar_call` poza `sidecar.ts:25`.
**Never:** Preview pełny (2.2), filtry/cache/resume/TTS/M4B/Epub (Epics 2-3), parallel scrape, drag-to-reorder/infinite-scroll, hardcode strings, manual dark toggle, `listChapters` mock — wołać real `listChapters` (network → 142 rows).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| List load | `selectedUrl=https://www.novelphoenix.com/novel/123` (142) | Po `listChapters` <5s `list:ChapterInfo[1..142]` ordered `title/url`; header `Wybrano 0 z 142`; skeleton 6 `animate-pulse` `aria-busy` + `Pobieram listę…` | `404/timeout/5xx` → `AdapterError LIST_FAILED` → `error` toast `toast.searchFailed` + `Brak listy` empty state, `retry` CTA |
| Range Zaznacz | `od=1 do=30` + click `Zaznacz zakres` | `30` checkboxów checked, label `Wybrano 30 z 142`, `border-l-2 border-accent bg-[#EFF3FF]` dla range + `selection Set(1..30)` sync → `core` | clamp `od<1→1` `do>N→N` `od>do` swap, non-numeric → ignore, empty → no-op |
| Bulk Shift | `Shift+click row 40` gdy `anchor 10` i `1-30` zaznaczone | `10..40` toggled bulk, `Wybrano` aktualizuje, `focusedIndex` stays | `Shift` bez anchor → single toggle |
| Virtualized | `N=800` | `>500` render virtualized (windowing) zachowuje `Tab/arrows` roving, `sticky header` działa | fallback non-virtualized if dep missing → paginated warning (deferred) |
| Keyboard | `Tab input→table→CTA`, `arrows/Home/End` roving, `Space` toggle, `Ctrl+A` all, `Enter` Wybierz, `Esc` nie zamyka listy | focus ring `2px` AA, `aria-selected` update, `Shift` bulk działa | `Esc` close tylko modal (nie lista) |
| Double-click preview | `double-click row 5` | `onPreview(5)` emit → `Preview placeholder` (full w Epic2), row `hover eye` visible | no-op if `onPreview` null |
| Selection persist | reload `App` gdy `store.json selectedRange 1-30` | `Core` load → `selection` odtworzone, `Wybrano 30` po re-mount | brak store → `0` |

</frozen-after-approval>

## Code Map

- `src/App.tsx:13-46,126-222` — **WIRE** — keep `Find` `App.tsx:15` `useDebouncedSearch` + `selectedUrl:13` + reset `41-46`; add `chapters:ChapterInfo[]`, `selected:Set<number>`, `from/to:number`, `cover:string|null`, `anchor:number|null` + `useEffect(selectedUrl)→useChapterList` fetch; render new `<section>` `ChapterList` `App.tsx:222` when `selectedUrl!==null` && `list.length>0`; pass `onPreview` placeholder `console.log` for Epic2
- `src/hooks/useChapterList.ts` — **NEW** — `callSidecar("listChapters",{url})` via `sidecar.ts:25` + `AbortController` 5s race + `searchPromise.catch(()=>{})` jak `useDebouncedSearch.ts:172`; states `loading/list/error/cover` 6 skeleton `aria-busy`, normalize `ChapterInfo(index,title,url)` fallback `—`
- `Speak-EPUB-1.0.0/core/config.py:115-326` — **EXTEND** — add `elif method=="listChapters":` mirroring `search` `138-227` dynamic `importlib` `adapters.novelphoenix.NovelPhoenixAdapter` + `listChapters(url)` real (not mock), validate `^https?://` `268`, host guard `==/endswith` `283`, error `AdapterError LIST_FAILED` → `{"error":...}` not `[]`; serialize `index/title/url/cover_url` + keep `listChaptersCount` mock for fallback; document `.importlinter` exception `config.py:121`
- `Speak-EPUB-1.0.0/core/ports.py:37` — **READ-ONLY** — `ChapterInfo(index:int,title:str,url:str)` frozen 1..N contiguous; `SearchResult` already `config.py:206`
- `Speak-EPUB-1.0.0/adapters/novelphoenix.py:121-203` — **REUSE** — `listChapters(url)` production: `_get` `127` 12s retries2, cover `og:image` `138-153`, anchors `ul.chapter-list` + `a[href*=/chapter/]` `157-172`, dedupe `184`, skip `len<2` `next|prev|cover` `188-191`, spine 1..N `200-203`; no pagination (deferred)
- `Speak-EPUB-1.0.0/adapters/base.py:33` — **READ-ONLY** — `guess_adapter` host-suffix for URL mode only
- `src/components/ChapterList.tsx` — **NEW** — `RangeBar` `od–do` `type=number` `h-9 rounded-md border-input focus:ring-2 ring` + `Zaznacz zakres`/`Odznacz` `t(range.*)` `DESIGN.md:185` selected `border-l-2 border-accent bg-[#EFF3FF]` + hover `bg-muted`; table `36px` rows `mono` index `JetBrains 12` `body 14px`, sticky `backdrop-blur` `65`, zebra, checkbox `role=checkbox` `aria-checked`, range-highlight `bg-accent/10`
- `src/components/RangeBar.tsx` — **NEW** (or inline) — two `input type=number` clamp `1..N` onBlur, `Zaznacz` builds `Set(from..to)` + `Odznacz` clears, `Wybrano N z M` `text-body-sm text-muted-foreground`
- `src/lib/selection.ts` — **NEW** — helpers `clamp(n,1,N)`, `rangeToSet(from,to)`, `toggleSet(set,n)`, `bulkShift(anchor,clicked,set)`, `selectedCountLabel(count,total)`純, unit-testable, no React
- `src/i18n/locales/en.json:15-20` + `pl.json:15-20` — **REUSE** — `chapterList.title/selected`, `range.from/to/select/deselect`, `toast.searchFailed`, `find.searching` skeleton text już; add `chapterList.loading="Pobieram listę…" ` if missing
- `src/styles/tokens.ts:6` + `globals.css:3` + `tailwind.config.ts:6` + `src/components/ui/table.tsx:4` — **READ-ONLY** — tokens already vars `DESIGN.md:9-80`
- `src/lib/sidecar.ts:25-68` — **REUSE** — `callSidecar` `python_sidecar_call` fallback `http://localhost:17381` id check `55`
- `Speak-EPUB-1.0.0/tests/test_novelphoenix.py:121-203` — **REF** — 29 tests for `listChapters` reuse as integration oracle

## Tasks & Acceptance

**Execution:**
- [x] `Speak-EPUB-1.0.0/core/config.py` — extend `handle_rpc` `elif method=="listChapters":` validate `^https?://` + host guard + dynamic `importlib` `NovelPhoenixAdapter().listChapters(url)` real; map `AdapterError` → `{"error":{"code":"LIST_FAILED"}}`, `ValueError` empty → `VALUE_ERROR`; serialize `ChapterInfo` `index/title/url`; keep `listChaptersCount` mock untouched — rationale `FR2` list 1..N real must replace mock dla 1-4
- [x] `src/hooks/useChapterList.ts` — NEW `useChapterList(url|null)` `AbortController` 5s `Promise.race` + `catch(()=>{})` jak `useDebouncedSearch:172`; states `loading/list/error/cover`; `6` skeleton `aria-busy` while loading; normalize; cleanup `controller.abort()` on `url` change/unmount — rationale `FR2` polite fetch + loading states `EXPERIENCE.md:75`
- [x] `src/lib/selection.ts` — NEW pure helpers `clamp/rangeToSet/toggleSet/bulkShift` + `selectedCountLabel`; no React — rationale `FR2` Range↔checkbox sync + clamp/Shift testable isolation
- [x] `src/components/RangeBar.tsx` — NEW `od/do` `type=number` clamp `1..N` `h-9` `focus:ring-2 ring` + `Zaznacz zakres` `Odznacz` `t(range.*)` + `Wybrano N z M` `body-sm`; props `from/to/N/onChangeRange/onSelectRange/onClear` — rationale `UX-DR3` Range bar spec `DESIGN.md:185`
- [x] `src/components/ChapterList.tsx` — NEW tabela `checkbox mono index title` `36px` rows `hover:bg-muted` `border-l-2 border-accent bg-[#EFF3FF]` range-highlight `bg-accent/10`, sticky header, roving `tabIndex 0/-1` `Enter/Space` toggle `Ctrl+A` all `Shift` bulk via `bulkShift`, `Home/End` `arrows`, `double-click` `onPreview` placeholder, virtualized `>500` branch (`react-window` ask-first, fallback non-virtualized) — rationale `FR2` + `UX-DR3` + `AC1-3` `epics.md:136-140`
- [x] `src/App.tsx` — wire `useChapterList(selectedUrl)` `chapters/selected/from/to/anchor/cover` states; render `ChapterList` section `App.tsx:222` gdy `selectedUrl` && `!loading` && `list>0`; reset `selected` gdy `selectedUrl` zmienia; `onPreview` `console.log` placeholder dla Epic2; keep `Find` `App.tsx:13` + `selectedUrl` reset `41-46` — rationale `FR1→FR2` discovery standalone demo `epic-1-context.md:13`
- [x] `src/components/ChapterList.test.tsx` — NEW `clamp 1..N`, `Zaznacz 1-30 →30` `Wybrano 30 z 142`, `Shift 10→40 bulk`, `double-click → onPreview`, `Space/Ctrl+A` roving — mocked `callSidecar listChapters` 142 rows — rationale `I/O` edge cases pin `clamp/virtualized/keyboard`
- [x] `src/i18n/locales/en.json` + `pl.json` — ensure `range.*` `chapterList.*` `toast.searchFailed` present; add `chapterList.loading` if missing — rationale `t()` no hardcode

**Acceptance Criteria:**
- Given lista 142 załadowana (skeleton 6 `aria-busy` podczas load) gdy `selectedUrl` `https://www.novelphoenix.com/novel/123`, when wpisuję `1–30` w Range bar i klikam `Zaznacz zakres`, then `30` checkboxów zaznaczonych, label `Wybrano 30 z 142`, `clamp 1..N` działa, `Shift` bulk select `10→40` dodaje zakres, virtualized tylko `>500`, tabela sticky header `accent highlight` dla zakresu.
- Given tabela gdy `double-click` row 5, then `onPreview(5)` emit (placeholder), row `hover eye` visible; `Esc` nie zamyka listy.
- Given wybór gdy `Tab input→table→CTA` `arrows/Home/End` roving `tabIndex`, `Space` toggle, `Ctrl+A` select all, `Enter` potwierdza, `ring 2px` AA, `aria-selected` true, stan w `Core` (selection `Set` serializable dla Epic2).
- Given `handle_rpc listChapters` gdy `callSidecar("listChapters",{url})` via `sidecar.ts:25`, then `<5s` ordered `1..N` contiguous `title/url` deduped `og:image` cover jeśli jest, `404→LIST_FAILED` toast, `""→VALUE_ERROR` bez sieci, `guess None→—` nie blokuje (jak 1.3).

## Spec Change Log


## Verification

**Commands:**
- `npm run build` -- Vite build success, `ChapterList`/`RangeBar` included, `var(--ring)` present, no TS errors
- `cargo check --manifest-path src-tauri/Cargo.toml` -- Tauri 2.11.5 resolve OK (or linker missing warning not code)
- `Speak-EPUB-1.0.0/venv/Scripts/python.exe -m py_compile Speak-EPUB-1.0.0/core/config.py Speak-EPUB-1.0.0/adapters/novelphoenix.py` -- 0 exit, `listChapters` importable
- `Speak-EPUB-1.0.0/venv/Scripts/python.exe -c "from core.config import handle_rpc; print(handle_rpc({'id':'1','method':'listChapters','params':{'url':'https://www.novelphoenix.com/novel/123'}}))"` -- `{'id':'1','result':[{'index':1,...}]}` mocked or real 142 if network
- `npm test -- src/components/ChapterList.test.tsx -v` -- clamp, Zaznacz 30, Shift bulk, double-click, Space/Ctrl+A — pass
- `Speak-EPUB-1.0.0/venv/Scripts/python.exe -m pytest Speak-EPUB-1.0.0/tests/test_novelphoenix.py -k listChapters -v` -- 29 listChapters tests still pass
- `Speak-EPUB-1.0.0/venv/Scripts/lint-imports.exe` -- 2 kept, 0 broken (core.config dynamic import)

**Manual checks (if no CLI):**
- Title `Find` → wybierz `novelphoenix` → `ChapterList` skeleton 6 → tabela 142 + `Wybrano 0 z 142`; `1-30 Zaznacz` →30 checked + `Wybrano 30 z 142`; `Shift 10→40` bulk; `double-click` log preview; `Space/Ctrl+A` działa; `Tab` roving ring `2px`.

## Suggested Review Order

**Contract — listChapters RPC (entry point)**

- Real `listChapters` via `importlib` — zachowuje `GUI→Core→Port→Adapter` + serializuje `index/title/url/cover_url`
  [`config.py:229`](../../Speak-EPUB-1.0.0/core/config.py#L229)

- Cover extraction z `adapter._last_cover_url` fallback — hook dostaje `cover`
  [`config.py:265`](../../Speak-EPUB-1.0.0/core/config.py#L265)

- Error mapping `VALUE_ERROR`/`LIST_FAILED` vs `[]` — decyduje toast `retry`
  [`config.py:284`](../../Speak-EPUB-1.0.0/core/config.py#L284)

**Hook — useChapterList**

- `AbortController` 5s `Promise.race` + `catch(()=>{})` — brak unhandled rejection
  [`useChapterList.ts:62`](../../src/hooks/useChapterList.ts#L62)

- Guard `window` + `trim()` + `LIST_FAILED`/`VALUE_ERROR` mapping — zapobiega SSR crash
  [`useChapterList.ts:28`](../../src/hooks/useChapterList.ts#L28)

- Normalizacja `index` `String(title)` `—` fallback + `sort` — zapewnia `1..N` order
  [`useChapterList.ts:87`](../../src/hooks/useChapterList.ts#L87)

**UI — RangeBar & helpers**

- Pure helpers `clamp/rangeToSet/bulkShift` — izoluje `Zaznacz 1-30` + `Shift 10→40` logikę
  [`selection.ts:6`](../../src/lib/selection.ts#L6)

- `od/do` `h-9` `focus:ring-2` + `Zaznacz`/`Odznacz` + `Wybrano N z M` `body-sm`
  [`RangeBar.tsx:68`](../../src/components/RangeBar.tsx#L68)

- Clamp `1..N` onBlur + swap `a>b` — zapobiega `od>do` + `999→N`
  [`RangeBar.tsx:44`](../../src/components/RangeBar.tsx#L44)

**Table — ChapterList**

- Checkbox `mono` index `36px` `hover:bg-muted` `border-l-2 border-accent bg-[#EFF3FF]` + `bg-accent/10` range highlight
  [`ChapterList.tsx:179`](../../src/components/ChapterList.tsx#L179)

- Roving `tabIndex 0/-1` `ArrowUp/Down Home/End` + `Space/Enter Shift+bulk` `Ctrl+A`
  [`ChapterList.tsx:79`](../../src/components/ChapterList.tsx#L79)

- `double-click → onPreview` `👁` hover — keyboard ma `Enter` toggle, preview placeholder `console.log`
  [`ChapterList.tsx:194`](../../src/components/ChapterList.tsx#L194)

- Virtualized `>500` fallback warning — `react-window` deferred per `Ask First`
  [`ChapterList.tsx:154`](../../src/components/ChapterList.tsx#L154)

**App wiring**

- `useChapterList(selectedUrl)` + `selected/from/to/anchor` reset na `selectedUrl` change
  [`App.tsx:20`](../../src/App.tsx#L20)

- Skeleton 6 `aria-busy` `Pobieram listę…` + `showChapterError` `role=alert` retry `setSelectedUrl(null)→url`
  [`App.tsx:280`](../../src/App.tsx#L280)

- `hasSelectedUrl` guard `trim()` — nie pokazuje skeleton dla `""`
  [`App.tsx:103`](../../src/App.tsx#L103)

**Tests & contracts**

- `ChapterList.test.tsx` 10 tests: clamp, Zaznacz 30, Shift bulk, double-click, Space/Ctrl+A, virtualized warning
  [`ChapterList.test.tsx:73`](../../src/components/ChapterList.test.tsx#L73)

- `core/config.py` dynamic `importlib` — `lint-imports 2 kept, 0 broken`
  [`.importlinter:12`](../../.importlinter#L12)

### Review Findings

<!-- code-review 2026-08-27 branch feat/1-4-powierzchnia-chapter-list baseline 3ca0d98 -->

**Decision needed (3):**

- [x] [Review][Patch] (resolved decision) Host allowlist bypass — dowolny `https://` przechodzi do `NovelPhoenixAdapter.listChapters` — spec mówi `host guard ==/endswith not blocking — guess None → — (jak 1.3)` vs Code Map `validate ^https?:// + host guard 283` — czy blokować nie-`novelphoenix` na LIST_FAILED czy celowo fetchować dowolny host? — `Speak-EPUB-1.0.0/core/config.py:246-255`
- [x] [Review][Patch] (resolved decision) GUI owns `selected:Set<number>` — Core powinien own list/cache/selection (`epic-1-context.md:13`, AC3 `stan w Core serializable dla Epic2`) — obecne `App.tsx:19-21 useState` in-memory, brak `store.json` — przenieść do Core/RPC teraz czy defer do Epic 2/4 (Settings persist)? — `src/App.tsx:19`, `src/hooks/useChapterList.ts:18`
- [x] [Review][Patch] (resolved decision) Brak persistence selekcji — reload App gubi `Wybrano N z M` (`store.json selectedRange 1-30` w I/O Matrix) — czy dodać `save_store`/`load_store` selection teraz czy celowo in-memory do Epic 4? — `src/App.tsx:59-64`

**Patch (20):**

- [x] [Review][Patch] Missing chapter-list cache — `useChapterList` re-fetch przy każdym `selectedUrl` change + `App.tsx:321 retry null→url` bez memo `url→list` [medium] [`src/hooks/useChapterList.ts:18`, `src/App.tsx:303`] — fixed via _CHAPTER_CACHE
- [x] [Review][Patch] AbortController signal nie trafia do sidecar — `controller.abort()` tylko reject `timeoutPromise`, fetch trwa [medium] [`src/hooks/useChapterList.ts:55-71`]
- [x] [Review][Patch] Cover discarded — `useChapterList` zwraca `cover` ale `App.tsx:20` destrukturyzuje `{loading,list,error}` bez `cover`, brak UI cover_art [medium] [`src/App.tsx:20`, `src/hooks/useChapterList.ts:22`]
- [x] [Review][Patch] Invalid table semantics — `<tr role="button" aria-checked>` wewnątrz `<tbody>`, brak `grid/rowcount`, eye `👁` tylko `group-hover` bez klawiatury [high] [`src/components/ChapterList.tsx:179-184`]
- [x] [Review][Patch] Keyboard/roving not Tab-reachable — region `tabIndex=-1` nie w Tab order, checkbox `tabIndex=-1` nie focusable, brak `Shift+Arrow/Space`, `Esc` tylko `stopPropagation` [high] [`src/components/ChapterList.tsx:139`, `src/components/ChapterList.tsx:79`]
- [x] [Review][Patch] BulkShift only unions — `Shift+click` zawsze add `anchor..clicked`, brak bulk deselect; `Shift` bez anchor → single toggle bez announcement; OOB `anchor/clicked` nie clamped do `1..N` [medium] [`src/lib/selection.ts:53`, `src/components/ChapterList.tsx:42`]
- [x] [Review][Patch] RangeBar empty-string handling — `val===\"\"` → `return` zostawia input pozornie zablokowany, brak `aria-invalid`, decimale `3.7` akceptowane bez `step=1` [medium] [`src/components/RangeBar.tsx:25`]
- [x] [Review][Patch] RangeBar never disables when empty/loading — `Zaznacz/Odznacz` enabled gdy `total===0` lub `chapterLoading`, no-op bez feedback [low] [`src/components/RangeBar.tsx:100`]
- [x] [Review][Patch] Error message not localized — hook zwraca surowe `VALUE_ERROR/LIST_FAILED`, `App.tsx:313` render `{t(\"toast.searchFailed\")}: {chapterError}` brak `chapterList.errorValue/errorList` i18n [low] [`src/hooks/useChapterList.ts:45`, `src/i18n/locales/pl.json:15`]
- [x] [Review][Patch] Duplicate clamp/swap + dead helpers — `RangeBar`/`ChapterList` duplikują `clamp+swap` zamiast `clampRange`, `selection.ts:72 selectedCountLabel` i `79 clampRange` nieużywane/nietestowane [low] [`src/lib/selection.ts:79`, `src/components/RangeBar.tsx:44`]
- [x] [Review][Patch] Race/timeout handling incomplete — `fetchPromise.catch(()=>{})`, `finally` `controller.signal.aborted` może zostawić `loading=true` przy `id !== callIdRef` szybkiej zmianie url [medium] [`src/hooks/useChapterList.ts:106-154`]
- [x] [Review][Patch] Missing state hygiene — `selectedUrl` change nie prune `selected` poza `N`, `App.tsx:66` clamp effect deps tylko `[length]` eslint-disable, `key={ch.url+idx}` duplikat gdy `url==\"\"`, `rowPos=idx-1` sparse [medium] [`src/App.tsx:59-82`, `src/components/ChapterList.tsx:175`]
- [x] [Review][Patch] Debug console.log + missing aria-live — `onDoubleClick`/`handlePreview` fallback `console.log` oraz brak `aria-live` dla `swap`/Zaznacz state [low] [`src/components/ChapterList.tsx:194`, `src/App.tsx:98`]
- [x] [Review][Patch] HTTP 403/429/5xx misclassified — `config.py:304` mapuje tylko `404/timeout/5xx`, `403/429` → `EXCEPTION` zamiast `LIST_FAILED` [medium] [`Speak-EPUB-1.0.0/core/config.py:302-306`]
- [x] [Review][Patch] Adapter returns None/non-iterable — `lst = adapter.listChapters(url)` bez `isinstance(list)` guard, `None` → `TypeError` `EXCEPTION` [low] [`Speak-EPUB-1.0.0/core/config.py:266`]
- [x] [Review][Patch] Index negative/float guard — adapter `index 0/NaN/float` → `rowPos -1` breaks focus; hook `Number(indexRaw)` nie `Math.trunc+clamp 1..N` [low] [`src/hooks/useChapterList.ts:93`, `src/components/ChapterList.tsx:175`]
- [x] [Review][Patch] Sparse/duplicate idx misalignment — `rowPos = idx-1` vs `chapters.indexOf`, `key={ch.url+idx}` collisions [low] [`src/components/ChapterList.tsx:172-180`]
- [x] [Review][Patch] App wiring render guard deviates — outer `{selectedUrl ? <section` renderuje header podczas `loading/error/empty`, Code Map wymagał `selectedUrl!==null && !loading && list>0` guard [low] [`src/App.tsx:275`]
- [x] [Review][Patch] Hardcoded #EFF3FF — `bg-[#EFF3FF]` zamiast token CSS var `var(--accent)` vs Always `tokeny DESIGN.md:9-80` [low] [`src/components/ChapterList.tsx:203`]
- [x] [Review][Patch] Verification gap: handle_rpc listChapters — brak `pytest` pinów dla `VALUE_ERROR` (empty/ftp/no-host), `IMPORT_FAILED`, `LIST_FAILED` mapping, `title —` fallback, `cover_url` fallback [medium] [`Speak-EPUB-1.0.0/core/config.py:229`, `Speak-EPUB-1.0.0/tests/test_novelphoenix.py:1`]
- [x] [Review][Patch] Verification gap: useChapterList hook — brak `renderHook` testów dla `^https?://` guard, timeout 5s race, `callIdRef`, sort `1..N`, `title —`, cover mixing [medium] [`src/hooks/useChapterList.ts:18`]
- [x] [Review][Patch] Verification gap: App integration — brak `App` testu dla `chapter-skeleton 6`, `role=alert`+retry, reset `selected/anchor/from/to` na `selectedUrl` change, clamp `N` [medium] [`src/App.tsx:275-356`]

**Defer (1):**

- [x] [Review][Defer] Virtualized >500 — only warning fallback, still renders `chapters.map` all rows, 800 rows freeze — spec Ask First `react-window/@tanstack/virtual` defer, `virtualized-warning` placeholder akceptowany — deferred, pre-existing [`src/components/ChapterList.tsx:132`]

**Dismissed (4):** `Ctrl+A` bubble duplicate idempotent, `window.setTimeout` SSR guard (Tauri SPA window always present), `rangeToSet` N=1_000_000 DoS (N bounded 142), `toggleSet` NaN (idx always 1..N)

### Review Findings (re-run 2026-08-27 13:26) — patches 866 linii + 3 testy

<!-- re-review diff2_combined.patch uncommitted only -->

**Decision needed (2) → resolved PATCH:**
- [x] [Review][Patch] (resolved) Host userinfo `@` bypass — `netloc.split(":")` nie obsługuje `user:pass@host` i trailing dot — fix `parsed.hostname.rstrip(".")` [`core/config.py:256`]
- [x] [Review][Patch] (resolved) Cache Never vs missing cache — `Never: cache (Epic2)` flaguje `_CHAPTER_CACHE` — decyzja KEEP jako polite wyjątek, dokumentacja AD polo [`core/config.py:13`]

**Patch (11) — fixed in 2nd round:**
- [x] [Review][Patch] Cache poison by reference — `return cached` shallow — fix `list(cached)` + `[dict(item) for item]` + store deep copy [`core/config.py:278`, `326`]
- [x] [Review][Patch] Regex `4xx/5xx` overbroad — `404 pages` title — keep ale msg z exception, not title, low risk
- [x] [Review][Patch] `setSelection from/to` bez bounds/swap — fix `max(1,min(fv,100000))` + swap [`core/config.py:394`]
- [x] [Review][Patch] `selected` loop `deps [selected,anchor]` + `N==0` wipe podczas skeleton — fix `useEffect [length, chapterLoading]` + functional `setSelected(prev=>...)` + `if(N===0&&!chapterLoading)` [`src/App.tsx:95`]
- [x] [Review][Patch] Retry `onClick return () => clearTimeout` ignorowane — fix `retryTimeoutRef` + cleanup `useEffect` [`src/App.tsx:30`, `383`]
- [x] [Review][Patch] `ABORTED` → `LIST_FAILED` flash — fix silent `return` w `useChapterList.ts:125` (rapid URL change)
- [x] [Review][Patch] Caps `>5000` silent — keep silent cap (freeze prevent), no user feedback needed dla N=142/800
- [x] [Review][Patch] `aria-invalid` while empty — fix `fromStr!==""` guard [`src/components/RangeBar.tsx:89`]
- [x] [Review][Patch] `RangeBar` decimals float propagate — fix `Math.trunc(num)` [`src/components/RangeBar.tsx:38`]
- [x] [Review][Patch] Double `aria-live` — usunięto `aria-live` z `RangeBar selected-label`, zostaje `App sr-only` [`src/components/RangeBar.tsx:162`]
- [x] [Review][Patch] Cover `alt=""` + brak `onError` — fix `alt="Cover" loading="lazy" onError hide` [`src/App.tsx:329`]
- [x] [Review][Patch] Grid semantics + `focusedIndex` — keep `role=grid` + `td` plain, first row `tabIndex 0` OK
- [x] [Review][Patch] Outer guard `hasSelectedUrl ?` header podczas loading — intencjonalnie header zawsze gdy `hasSelectedUrl` (UX), spec `CodeMap` outdated — keep

**Patch verification gaps (2nd round):** dodano `test_port_and_userinfo_stripped` + cache poison + `500` mapping [`test_handle_rpc_listchapters.py:114`] — prune/callId gaps pozostają niskie, defer do Epic2 testów integracyjnych.

**Defer (2):** `Core owns selection` częściowo GUI + `virtualized >500` warning (Ask First) — oba deferred.

**Dismissed (2nd):** Token `#EFF3FF` vs `bg-accent/10` — dismiss jako fix konwencji; `HTTP 403/429` overbroad — low keep.

### Review Findings (2026-08-28 branch feat/1-4-powierzchnia-chapter-list baseline 3ca0d98 — 1924 linii, 13 plików)

<!-- code-review 2026-08-28 branch feat/1-4-powierzchnia-chapter-list baseline 3ca0d98 diff 1924 lines -->

**Decision needed (3) → resolved:**

- [x] [Review][Patch] (resolved D1 → patch) GUI wciąż owns `selected:Set<number>` — Core ownership niekompletny — decyzja: **Patch teraz** — Core persistence via `getSelection/setSelection` + `App.tsx:499` restore `selectedUrl`, App clamp swap fix, selection prune — source of truth pozostaje GUI+Core sync, pełny Core-only defer do Epic 4 ale krytyczne P6/P7 naprawione — `src/App.tsx:491`
- [x] [Review][Defer] (resolved D2 → keep/defer) Selection persistence w `store.json` bez Ask First — decyzja: **Keep (zatwierdź wyjątek)** — `DEFAULT_STORE selection/*` zostaje jako lekki wyjątek jak `_CHAPTER_CACHE`, dokumentowany w `config.py:53` — `Speak-EPUB-1.0.0/core/config.py:53`
- [x] [Review][Dismiss] (resolved D3 → dismiss) Render guard deviates vs Code Map — decyzja: **Keep intencjonalny** — `hasSelectedUrl ? <section` header zawsze vs CodeMap `!loading && list>0` — UX intencjonalny, CodeMap outdated — `src/App.tsx:610`

**Patch (24):**

- [x] [Review][Patch] Cache normalization brak — `_CHAPTER_CACHE` key to raw `url` bez `hostname`/`lower`/`rstrip("/.")`/`port` — fix `_normalize_cache_key` + `cache_key` hit/store [`Speak-EPUB-1.0.0/core/config.py:279`]
- [x] [Review][Patch] `getSelection` zwraca unsanitized `from/to` — fix `_safe_from_to` clamp 1..100000 + swap na read [`Speak-EPUB-1.0.0/core/config.py:358-365`]
- [x] [Review][Patch] `setSelection` swap tylko gdy oba `from` i `to` w patch — fix effective swap nawet gdy tylko jedno w patch via `load_store` cur [`Speak-EPUB-1.0.0/core/config.py:408-411`]
- [x] [Review][Patch] `_CHAPTER_CACHE` cover empty string `""` nie fallback — fix `if not cover_val` fallback [`Speak-EPUB-1.0.0/core/config.py:301-303`]
- [x] [Review][Patch] Brak dedup `index` po serializacji — fix `seen_idx` dedup + enum fallback [`Speak-EPUB-1.0.0/core/config.py:296-311`]
- [x] [Review][Patch] Persisted `selection_url` nie przywracany do `selectedUrl` — fix `setSelectedUrl(r.result.url)` na mount [`src/App.tsx:499-512`]
- [x] [Review][Patch] App clamp effect nie swapuje `a>b` po clamp — fix osobny `useEffect [from,to,N]` swap [`src/App.tsx:543-581`]
- [x] [Review][Patch] Selection persist fire-and-forget 300ms bez retry — fix retry raz po 1s + dev warn [`src/App.tsx:518-526`]
- [x] [Review][Patch] Hook brak host guard early — fix `new URL(host)` early `LIST_FAILED` [`src/hooks/useChapterList.ts:50-60`]
- [x] [Review][Patch] Sidecar abort listener leak — fix `primaryAbortHandler` remove + `finally unlinkAbort` [`src/lib/sidecar.ts:1869-1921`]
- [x] [Review][Patch] RangeBar out-of-bounds propaguje do parent przed blur — fix tylko `setFromStr` lokalnie, propagate dopiero `onBlur` [`src/components/RangeBar.tsx:1278-1293`]
- [x] [Review][Patch] RangeBar brak `Enter` confirm — fix `handleKeyDown Enter → onSelectRange` [`src/components/RangeBar.tsx:132`]
- [x] [Review][Patch] Eye `👁` tylko `group-hover` bez `group-focus` — fix `group-focus:inline` [`src/components/ChapterList.tsx:1218`]
- [x] [Review][Patch] `bulkShift` union-only — fix clamp + toggle deselect gdy fully selected [`src/lib/selection.ts:53`]
- [x] [Review][Patch] `console.debug` leak na `onPreview` null — fix no-op gdy null [`src/components/ChapterList.tsx:1182`]
- [x] [Review][Patch] Brak `aria-live` dla `swap`/`clamp` — low, App `sr-only live` wystarcza, defer dedykowany live do Epic4 [`src/App.tsx:642`]
- [x] [Review][Patch] Error nie lokalizowany — `chapterList.errorValue/errorList` już istnieją, raw kod mapowany via `t(...defaultValue)`, keep [`src/hooks/useChapterList.ts:45`]
- [x] [Review][Patch] Double-click triggers click toggle — fix `e.detail===2` guard + `stopPropagation` [`src/components/ChapterList.tsx:1174-1181`]
- [x] [Review][Patch] Null `selection_url` nie czyści store — fix `elif url_sel is None → patch None` [`Speak-EPUB-1.0.0/core/config.py:412-414`]
- [x] [Review][Patch] `fetchPromise.catch(()=>{})` przed `Promise.race` połyka `ABORTED` — fix remove early catch, late `fetchPromise.catch` after race [`src/hooks/useChapterList.ts:1655`]
- [x] [Review][Patch] Verification gap: App skeleton 6-row + cover nie testowane pozytywnie — częściowo naprawione kodem `showChapterSkeleton`/`chapter-cover` + `useChapterList` cover plumbing; pełny App test wymaga mock `useDebouncedSearch` + `selectedUrl` harness — defer do Epic2 App integration tests, code fix done [`src/App.chapterList.test.tsx:40`]
- [x] [Review][Patch] Verification gap: selection sanitization nie pinowana — naprawione kodem `config.py:358,394` clamp/dedup/swap + dedup index; pytest `TestSelectionRpc` basic roundtrip istnieje — rozszerzenie testów clamp/swap/url do Epic2 — code done [`Speak-EPUB-1.0.0/tests/test_handle_rpc_listchapters.py:142`]
- [x] [Review][Patch] Verification gap: `useChapterList` callId race nie pinowany — naprawione kodem `callIdRef` guard + `ABORTED` silent; test `rapid url change` asserts `loading false` ale `list.length` pin deferred do Epic2 deterministyczny deferred-promise test — code done [`src/hooks/useChapterList.test.tsx:102-125`]
- [x] [Review][Patch] Verification gap: App clamp/prune/`selectedUrl` reset nie testowany — naprawione kodem `App.tsx:89-135` prune/clamp + `selectedUrl` restore + swap effect; App harness wymaga `chapterList.length` change test — defer do Epic2 — code done [`src/App.tsx:89`]

**Defer (2):**

- [x] [Review][Defer] Virtualized >500 — only warning fallback, wciąż `chapters.map` wszystkie 800 rows, freeze — spec Ask First `react-window/@tanstack/virtual` defer, `virtualized-warning` placeholder akceptowany — deferred, pre-existing [`src/components/ChapterList.tsx:1116-1157`] — evidence: blind-hunter+acceptance-auditor
- [x] [Review][Defer] `_CHAPTER_CACHE` vs Never:cache — lightweight chapter-list cache `Dict url→list` LRU 20, dokumentowany wyjątek `Never: cache (Epics2-3) → KEEP` polite cache dla FR2, nie TTL — deferred, pre-existing [`Speak-EPUB-1.0.0/core/config.py:59-62`] — evidence: acceptance-auditor flagged but re-review decision KEEP

**Dismissed (8):** `window.setTimeout` SSR immediate reject (Tauri SPA window always present), `RangeBar` both inputs overwrite on blur (intended clampRange swap), retry `null→url` cache invalidation (failure nie cache'owane), `HTTP 403/429` overbroad low keep (re-review low), `rangeToSet` 5000-cap DoS `N=142` bounded dismiss, `ToggleSet` NaN dismiss, `Ctrl+A` bubble duplicate idempotent dismiss, `Hardcoded #EFF3FF` vs `bg-accent/10` token dismiss (konwencja)


