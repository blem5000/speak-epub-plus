---
title: 'Filtry — plain+regex na etapie EPUB build'
type: 'feature'
created: '2026-08-28'
status: 'done'
review_loop_iteration: 0
context:
  - _bmad-output/planning-artifacts/architecture/architecture-speak-epub-2026-08-27/ARCHITECTURE-SPINE.md
  - _bmad-output/implementation-artifacts/epic-2-context.md
  - _bmad-output/planning-artifacts/epics.md
warnings: []
---

<intent-contract>

## Intent

**Problem:** After selector isolation in `core/clean.py` the pipeline still ships subscription/nag lines into EPUB and TTS because no filter gate exists — e.g. `Subscribe` (plain) and `subscribe.*patreon` (regex) must be stripped once at EPUB build after `clean_html`, while raw cache `_cache/<sha1>/raw.html` (AD-9) must stay unfiltered (AD-2 invariant) and GUI must expose CRUD with live average and per-chapter preview chips.

**Approach:** Add Core-owned `core/filters.py` (plain `contains` + regex `re.search` line-wise, compiled once, applied once after selector isolation) consumed by `core/config.py` RPC `getFilters/saveFilters/addFilter/removeFilter` + extended `previewChapter` (returns filtered html/text + removed count) and future `core/epub.py` (2.4); persist `filters[]` via `store.json` atomic `save_store`, and build `Filters` panel + Preview chip + average badge in GUI.

## Boundaries & Constraints

**Always:** `GUI→Core→Port→Adapter` AD-1 — `core/filters.py` pure, no adapter imports; `core/config.py` RPC uses dynamic `importlib` for `core.clean`/`core.filters` (documented `.importlinter` exception); `raw` never filtered AD-2 (filter applies to `cleaned_text` only, original stays); filter gate idempotent and applied once per `cleaned_text` before EPUB/TTS (AD-2, AD-8); `store.json` `filters[]` shape `{pattern:string,isRegex:boolean}` persisted via `load_store`/`save_store` atomic `tmp.replace` AD-10; compile regex once per call and cache; `re.sub \s+` already in clean, filters do not alter whitespace; i18n via `t()` no hardcode; `JetBrains 12` mono for inputs; persist on blur, no save button.

**Ask First:** Change of `filters[]` JSON shape or storage location (store.json vs Rust store), regex flags (case-sensitive default vs `(?i)`), line semantic (remove whole line vs substring), max filters count/length, add Types/Scopes beyond plain/regex.

**Never:** Modify `core/fetch.py` politeness/cache/resume (2.1), overwrite `core/clean.py` selector/heuristic logic (2.2) or `adapters/novelphoenix.py:298 getSelectors`; add parallel scrape or move filter to fetch/TTS chunker; filter raw cache or write filtered back to `_cache`; introduce drag-to-reorder/infinite scroll; bypass `port` for chapter content fetch — cover/metadata direct fetch in `core/epub.py` is an explicitly **documented exception** (reconciled 09-02-2026 per triage D4 / epic-2 retro item-16: single-URL demo fetch with UA; port-surface cost not justified).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Plain hit | `cleaned="Intro\nSubscribe to read\nNext"` + `[{pattern:"Subscribe",isRegex:false}]` | `filtered="Intro\nNext"` removed 1, `filtered_html` without that line | N/A |
| Regex hit | `cleaned="Support on patreon.com/subscribeX\nHello"` + `[{pattern:"subscribe.*patreon",isRegex:true}]` (case-sensitive) | line removed if `re.search` matches; removed 1; regex matched via `re.compile(pattern)` without flags | N/A |
| Combined | both filters, `cleaned` contains both lines | each line checked against all filters OR (plain OR regex); removed 2, avg `2` | N/A |
| No filters | `filters=[]` | `filtered === cleaned`, removed 0, chip `0` | N/A |
| Empty text | `cleaned=""` | `filtered=""`, removed 0 | N/A |
| Raw invariant | `raw="<nav>Subscribe</nav><div id='chapter-content'>Hello</div>"` → `cleaned="Hello\nSubscribe"` after `clean_html` → `filtered="Hello"` | `read_cache(url)` still returns raw containing `Subscribe`, filtered/EPUB does not | assert `Subscribe in read_cache and not in filtered` |
| Invalid regex | `pattern="[*"` `isRegex:true` | `apply_filters` raises `ValueError("invalid regex: ...")` → RPC `VALUE_ERROR` muted chip, keep previous filtered | GUI shows muted error, save blocked |
| Duplicate/invalid persistence | `addFilter` duplicate pattern+type | dedup, no second entry; invalid empty pattern → `VALUE_ERROR` | N/A |
| Override+filter | selector override active, then filter | filters apply after `resolve_selectors` + `clean_html` (isolated text) not before | N/A |
| Long text preview | 8000 chars | preview truncates `originalText[:8000]` already, filtered preview uses same `clean_html` then filters, chip live <300ms | N/A |

</intent-contract>

## Code Map

- `Speak-EPUB-1.0.0/core/filters.py` — **NEW** — `Filter = {pattern:str,isRegex:bool}`, `compile_filters(filters)->list[Compiled]`, `apply_filters(cleaned_text:str,filters:list[dict])->tuple[str,int]` line-wise remove if `pattern in line` (plain) or `regex.search(line)` (regex, case-sensitive, no flags unless (?i) in pattern), `count_removed(cleaned,filtered)`; pure AD-2, compiled once, idempotent
- `Speak-EPUB-1.0.0/core/config.py:41` — **READ-ONLY** — `DEFAULT_STORE filters:[]`; `:104 load_store`, `:118 save_store` atomic; extend handle_rpc with `getFilters/addFilter/updateFilter/removeFilter/saveFilters` + extend `previewChapter:979` to apply `core.filters.apply_filters` after `clean_html` and return `filteredHtml/filteredText/removedCount/removedLines`
- `Speak-EPUB-1.0.0/core/clean.py:147` — **REUSE** — `clean_html(raw,start,end)->(html,text)` isolation entry; filters consume its `text`/`html` not raw; heuristic fallback unchanged
- `Speak-EPUB-1.0.0/core/fetch.py:56` — **REUSE** — `read_cache/get_cache_path` raw invariant `_cache/<sha1>/raw.html` never filtered
- `Speak-EPUB-1.0.0/core/ports.py:14` — **READ-ONLY** — `Selectors`, `ChapterContent`; not touched
- `Speak-EPUB-1.0.0/adapters/novelphoenix.py:298` — **READ-ONLY** — `getSelectors()->Selectors(start="div#chapter-content")` source
- `src/lib/sidecar.ts:25` — **EXTEND** — `callSidecar` generic + `getFilters/addFilter/removeFilter/previewChapter` wrappers with `trim` + strict `isFiltersResult` guard like `isPreviewResult:299`
- `src/components/Preview.tsx:285` — **EXTEND** — split 40/60 tabs `Original/Cleaned`, add `Filtered` tab? keep 2 tabs but add chip `data-testid="filter-chip"` showing `removed N` + live re-parse via debounced `previewChapter` 300ms `seqRef`; `Reset do adaptera` stays, filtered recomputed after filter change
- `src/components/Filters.tsx` — **NEW** — table `type badge plain/regex + phrase + x`, Input `data-testid="filter-input"` + toggle `isRegex` + `Add` button, delete `data-testid="filter-delete-<idx>"`, live `avgRemoved` `data-testid="filter-avg"` computed as `totalRemoved/numChaptersSample` or `removed/len(filters)`, persist on blur via `saveFilters` atomic
- `src/App.tsx:613` — **EXTEND** — host `Filters` panel behind gear or below Queue minimal; wire `handlePreview` filtered chip
- `src/i18n/locales/en.json:29` + `pl.json:39` — **EXTEND** — keys `filters.title`, `filters.add`, `filters.plain`, `filters.regex`, `filters.avg`, `filters.chip`, `filters.invalidRegex`
- `Speak-EPUB-1.0.0/tests/test_filters.py` — **NEW** — `apply_filters` plain/regex/combined/no-filters/empty/invalid/rawInvariant/overrideInteraction + dedup + compiles once (mock `re.compile` count)
- `Speak-EPUB-1.0.0/tests/test_handle_rpc_filters.py` — **NEW** — `getFilters/add/remove/save`, `VALUE_ERROR` invalid regex/empty, `previewChapter` filtered vs original filtered invariant, `store.json` atomic persistence via `tmp_path` isolate
- `src/components/Filters.test.tsx` — **NEW** — add plain/regex, delete, invalid blocked, avg `usuwa średnio 2 linie/rozdz.` calculation, persist on blur `saveFilters` called, Preview chip `removed N`

## Tasks & Acceptance

**Execution:**
- [x] `Speak-EPUB-1.0.0/core/filters.py` — NEW `APPLY_FILTERS_GATE` plain case-sensitive `in` + regex `re.search` (no flags unless inline `(?i)`), line-wise removal `text.splitlines()` preserve order, `compile_filters` caches `re.compile` per pattern, raises `ValueError("invalid regex: {pattern}")` on `re.error`, idempotent `filtered==apply(apply(cleaned))`; no adapter import, pure
- [x] `Speak-EPUB-1.0.0/core/config.py` — EXTEND handle_rpc `getFilters` (load_store filters[] sanitized [{pattern:stripped,isRegex:bool}]), `addFilter` `{pattern,isRegex}` trim validate non-empty ≤200 chars, dedup (case-sensitive pattern+isRegex), atomic `save_store`, `removeFilter` by index/pattern, `saveFilters` bulk, `updateFilter`; extend `previewChapter` to load `filters=load_store().filters`, after `clean_html` call `apply_filters(cleaned_text,filters)` and return `filteredHtml` (html lines filtered analogously or via text->html fallback), `filteredText`, `removedCount`, `originalText`; `VALUE_ERROR` for invalid regex kept, raw invariant: never write filtered back to cache
- [x] `src/lib/sidecar.ts` — EXTEND `getFilters`, `addFilter`, `removeFilter`, `saveFilters` wrappers + `isFiltersResult` guard, mirror `previewChapter` param trimming & `urls` `trim` pattern; keep `callSidecar` id check + fallback `http://localhost:17381`
- [x] `src/components/Filters.tsx` — NEW panel: Table `site|type badge|phrase|×` (`data-testid="filters-table"`), Input `data-testid="filter-input"` mono, toggle `data-testid="filter-regex-toggle"` (plain/regex), `Add` disabled if empty/duplicate/invalid regex (muted `VALUE_ERROR`), Delete `data-testid="filter-delete-*"` immediate, `avg` badge `data-testid="filter-avg"` live `usuwa średnio ${avg} linie/rozdz.` computed from preview sample or stored counts, persist on blur via debounced `saveFilters` (300ms) toast `Zapisano`
- [x] `src/components/Preview.tsx` — EXTEND add chip `data-testid="filter-chip"` showing `Usunięto ${removedCount} linii` + `live` filtered diff; tabs keep `Original/Cleaned` but `Cleaned` now shows `filteredText` when filters present? Keep Original/Cleaned as before, add small badge in Cleaned header; live re-parse debounced 300ms calls `previewChapter({url,start,end})` which now includes `filtered*` + `removedCount`; invalid selector/filter shows muted error keep previous
- [x] `src/App.tsx` — EXTEND mount `Filters` panel (e.g. below Queue or gear modal) + wire Preview chip propagation; keep selection persistence `getSelection/setSelection` untouched
- [x] `src/i18n/locales/en.json` + `pl.json` — EXTEND add `filters.*` keys no hardcode strings
- [x] `Speak-EPUB-1.0.0/tests/test_filters.py` + `Speak-EPUB-1.0.0/tests/test_handle_rpc_filters.py` — NEW coverage for I/O matrix + raw invariant + RPC persistence; mock `store.json` via `tmp_path` + `load_store` override, assert `re.compile` called ≤ `len(filters)` once per `apply_filters`
- [x] `src/components/Filters.test.tsx` + update `src/components/Preview.test.tsx` — NEW GUI pin: add plain/regex, delete, invalid muted, avg calc, Preview chip; mock `sidecar` `vi.mock` pattern like `Preview.test.tsx:24`

**Acceptance Criteria:**
- Given filtry `Subscribe` plain i `subscribe.*patreon` regex w `store.json` gdy `previewChapter` woła `clean_html` → `apply_filters`, then `filteredText` nie zawiera linii z `Subscribe` ani `patreon` subscription, `originalText` nadal zawiera, `removedCount` = liczba linii usuniętych, `raw` w `_cache/<hash>/raw.html` nadal zawiera `Subscribe` (invariant AD-2)
- Given Filters UI gdy dodaję plain `Unlimited access` i regex `subscribe.*patreon` i usuwam via ×, then tabela aktualizuje się (`type badge` + `phrase` + `x`), `live count` `usuwa średnio ${avg} linie/rozdz.` aktualizuje się, `persist on blur` (`saveFilters`) zapisuje `store.json` `filters[]` atomic, brak save button
- Given Preview gdy filtr aktywny, then chip `Usunięto N linii` widoczny, tabs `Original` vs `Cleaned` diff pokazuje usunięcie, `Reset do adaptera` nie usuwa filtrów tylko selektory, filtry nakładane po izolacji selektorów

## Spec Change Log


## Design Notes

Filters are line filter: `cleaned_text.splitlines()` → `keep = not any( plain_pat in line or regex.search(line) for f in filters )` → `"\n".join(keep)`. For html, derive `filteredHtml` by filtering text lines or stripping `<p>` lines analogously; keep simple text comparison for epub check. Plain `contains` is case-sensitive (use `in`), regex case-sensitive unless pattern contains `(?i)`. Store shape canonical `{pattern: str trimmed, isRegex: bool}`; deduplicate by `f"{pattern}|{isRegex}"`. Compile once: `compiled = [(f, re.compile(f.pattern)) if isRegex else f]` cached per call. Invalid regex surfaces as `VALUE_ERROR` with `invalid regex` message, GUI muted. Raw invariant test: `assert pattern in read_cache(url) and pattern not in filtered`.

## Verification

**Commands:**
- `Speak-EPUB-1.0.0/venv\Scripts\python.exe -m py_compile Speak-EPUB-1.0.0/core/filters.py` -- 0 exit
- `Speak-EPUB-1.0.0/venv\Scripts\python.exe -m pytest Speak-EPUB-1.0.0/tests/test_filters.py -v` -- plain/regex/combined/empty/invalid/dedup/compile-once/rawInvariant -- pass
- `Speak-EPUB-1.0.0/venv\Scripts\python.exe -m pytest Speak-EPUB-1.0.0/tests/test_handle_rpc_filters.py -v` -- get/add/remove/save/previewFiltered VALUE_ERROR -- pass
- `Speak-EPUB-1.0.0/venv\Scripts\python.exe -m pytest Speak-EPUB-1.0.0/tests/test_handle_rpc_preview.py Speak-EPUB-1.0.0/tests/test_clean.py -v` -- still pass, preview includes filtered
- `npm test -- src/components/Filters.test.tsx -v` -- add/delete/avg/chip -- pass
- `npm test -- src/components/Preview.test.tsx -v` -- live chip pass
- `npm run build` -- Vite OK Filters included
- `cargo check --manifest-path src-tauri/Cargo.toml` -- Tauri 2.11.5 OK

**Manual checks (if no CLI):**
- Find → ChapterList 1–3 double-click → Preview chip `Usunięto 0`; add filter `Subscribe` plain → Preview Cleaned loses line, chip `Usunięto 1`, raw `_cache/.../raw.html` still contains `Subscribe` via `Get-Content`; add regex `subscribe.*patreon` → second line removed, Filters table badge `regex` + `×`; avg `usuwa średnio 2 linie/rozdz.`; persist: close app → reopen → filters still there (store.json).

## Spec Change Log

| Date | Change | Source |
|------|--------|--------|
| 09-02-2026 | D4 reconciliation: cover/metadata direct fetch (with UA) in `core/epub.py` documented as an explicit exception to the "bypass `port`" Never rule — single-URL demo fetch; port-surface cost not justified. Rule narrowed to: never bypass `port` for chapter content fetch. | action-item-triage-08-31-2026.md (D4), epic-2-retro-08-31-2026.md item-16 |

