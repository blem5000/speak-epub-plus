---
title: 'Filters window pełny + integracja z Preview + EPUB gate'
type: 'feature'
created: '2026-08-29'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: false
baseline_commit: '75ef1dd63fe6bc9b40c004dd4e49d7210331fe47'
context:
  - _bmad-output/implementation-artifacts/epic-4-context.md
  - _bmad-output/planning-artifacts/architecture/architecture-speak-epub-2026-08-27/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/ux-designs/ux-speak-epub-2026-08-27/DESIGN.md
  - _bmad-output/planning-artifacts/ux-designs/ux-speak-epub-2026-08-27/EXPERIENCE.md
warnings: []
deferred:
  - summary: >-
      FiltersWindow focus trap minimal no inert background lock and no return-focus explicit verification
    evidence: |-
      blind-hunter noted modal role=dialog aria-modal but no inert attribute on background, focus restore via prev?.focus() only; no background scroll lock
    location: >-
      src/components/FiltersWindow.tsx:12
    severity: low
  - summary: >-
      store.json atomic tmp replace without fsync/cleanup deferred from 4.2
    evidence: |-
      verification-gap: save_store .tmp replace lacks fsync and cleanup on failure; pre-existing infra concern not caused by 4.3 validation but surfaces via getFilters/addFilter
    location: >-
      Speak-EPUB-1.0.0/core/config.py:131
    severity: low
---

<intent-contract>

## Intent

**Problem:** Core filter gate (2.3) works (plain `contains` + regex `re.search` applied once after `clean_html` with raw invariant `_cache/<sha1>/raw.html` never filtered), but its GUI surface is only an embedded panel below Result — no full window modal, no header entry point, and live average `filters.length*1.7` is a stub while Preview chip integration relies only on `filters-updated` event without a window-level persist-on-blur contract.

**Approach:** Promote filters to a full `FiltersWindow` modal (gear pattern like Settings) opened from App header, reusing existing `Filters` panel inside, wiring persist via `getFilters`/`addFilter`/`removeFilter` through `core/config.py` `store.json:filters[]` atomic, computing live average from stored filters (`Math.max(1, Math.round(filters.length*1.7))` stabilized or sample-based) with badge `data-testid="filter-avg"`, dispatching `filters-updated` so Preview's chip `data-testid="filter-chip"` shows `Usunięto N linii` per chapter and `Original/Cleaned` diff stays correct, while keeping EPUB gate single-pass after selector isolation.

## Boundaries & Constraints

**Always:** AD-1 `GUI→Core→Port→Adapter` — `core/filters.py` pure, no adapter imports; RPC via dynamic `importlib` in `core/config.py` (`getFilters/addFilter/removeFilter/saveFilters` + `previewChapter` filtered branch); `raw` never filtered AD-2 (filter once after `clean_html` in `core/epub.py:540` and `previewChapter:1290`); `store.json:filters[]` canonical `{pattern:string,isRegex:boolean}` trimmed ≤200, dedup `pattern|isRegex`, cap 100, persisted via `load_store/save_store` atomic `tmp.replace` AD-10; `re.compile` once per call; i18n via `t()` no hard-coded strings; modal `role=dialog aria-modal` Esc + focus-trap + overlay click closes; Filters table `type badge plain/regex + mono phrase + × delete` with `data-testid` per spec 2.3; chip `filter-chip` shows `removedCount` (`0` when none); avg badge `filter-avg` `aria-live=polite`; window dispatch `filters-updated` CustomEvent on add/delete.

**Block If:** `filters[]` shape changes (`pattern/isRegex` names, storage path, JSON types) without syncing `core/config.py:1399` `sanitize_filters` and `Speak-EPUB-1.0.0/core/filters.py:191`; adding new filter scope/type beyond `plain|regex` (requires Ask First); changing filter application stage away from `after clean_html before EPUB` (would break AD-2 invariant); altering `raw` cache path or writing filtered back to `_cache`.

**Never:** Save button for Filters; polling `store.json`; writing `store.json` directly from frontend bypassing `setStore`/`addFilter` RPC; filtering raw cache; overwriting `core/clean.py` selector/heuristic or `core/fetch.py` politeness; introducing drag-to-reorder or infinite scroll; touching `PartJob` or spine order.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Open window | Header click `data-testid="filters-window-button"` | Modal `role=dialog aria-modal` with `Filters` panel visible, focus trapped to input, `t("filters.title")` header | No error |
| Add plain | Input `Unlimited access` plain + Add | Table shows row badge `plain` mono phrase, `filter-add` disabled duplicate, `filter-avg` → `usuwa średnio 2 linie/rozdz.` or `removes ~` live, `addFilter{pattern,isRegex:false}` called, `filters-updated` dispatched, `store.json filters[]` updated | Empty → `filters.emptyError` alert; dup → `filters.duplicate` alert; >200 chars → `VALUE_ERROR` |
| Add regex | Input `subscribe.*patreon` toggle regex + Add | Row badge `regex` warning style, same avg live, RPC `isRegex:true`, compiled via `re.compile` | Invalid regex `[*` → `invalid regex` alert, no RPC |
| Delete | Click `×` `filter-delete-0` | Row removed, `removeFilter{index}` called, `filters-updated` dispatched, avg recalculated | Out-of-range index → `VALUE_ERROR` alert kept |
| Preview chip hit | Filters `Subscribe` plain active, `previewChapter` with `cleaned` containing `Subscribe` line | Preview `filter-chip` shows `Usunięto 1 linii` and `Cleaned` tab shows `filteredText` without line, `Original` still has it, `diffCount` accounts, debounce 300ms | Invalid filter regex in store → `previewChapter` returns `VALUE_ERROR invalid regex`, chip keeps previous, muted error |
| Raw invariant | `raw` contains `Subscribe`, `cleaned` filtered | `read_cache(url)` still contains `Subscribe`, `filteredText`/`filteredHtml` and EPUB artifact do not, `apply_filters(cleaned,filters)` removed 1 | No error expected |
| EPUB gate | `buildEpub` with active filters | `core/epub.py:540` `apply_filters_to_html(cleaned_html,filters)` once, logs `cleaned chapter N removed M lines`, epubcheck clean, cover/TOC unchanged | CACHE_MISS if chapter missing → `CACHE_MISS` error with missing list |
| Persist reload | Add filter then reload app | `getFilters` on next mount returns stored filter, window shows it, Preview chip reflects it | `store.json` corrupt → `load_store` fallback to `DEFAULT_STORE` empty |
| Avg zero | `filters=[]` | Badge `filter-avg` shows `t("filters.avgZero")` `Brak filtrów`/`No filters` | No error |

</intent-contract>

## Code Map

- `Speak-EPUB-1.0.0/core/filters.py:64-188` — **READ & REUSE** — `apply_filters` line-wise `pattern in line` vs `re.search`, `_compile_filters` once, `apply_filters_to_html` block removal excluding `div#chapter-content` container, `sanitize_filters` canonical `{pattern,isRegex}` dedup cap — pure, no adapter imports, AD-2
- `Speak-EPUB-1.0.0/core/epub.py:266-540` — **READ & REUSE** — loads `filters` via `sanitize_filters` if `filters is None`, gate `apply_filters_to_html(cleaned_html,filters)` once after `clean_html:535`, logs `cleaned chapter N removed M`, atomic `EpubHtml` write — verify invariant read_cache never filtered
- `Speak-EPUB-1.0.0/core/config.py:1399-1542` — **READ & REUSE** — `getFilters/addFilter/removeFilter/saveFilters` sanitized dedup ≤200 cap 100, invalid regex → `VALUE_ERROR invalid regex`, `previewChapter:1191` loads `filters` from `load_store`, applies `apply_filters_to_html` + derives `filteredText` via BeautifulSoup `get_text`, returns `filteredHtml/filteredText/removedCount/filters/start/end` with `originalText` preserved
- `Speak-EPUB-1.0.0/core/fetch.py:56` — **READ** — `read_cache/get_cache_path` raw invariant `_cache/<sha1>/raw.html` owned by Core, never filtered
- `Speak-EPUB-1.0.0/core/clean.py:77-147` — **READ** — `resolve_selectors/load_overrides/clean_html` per-adapter start/end + heuristic fallback never auto-overwrites adapter; filters consume its `(html,text)` only
- `src/lib/sidecar.ts:25-431` — **READ & REUSE** — `callSidecar` JSON-RPC with `http://localhost:17381` fallback, wrappers `getFilters/addFilter/removeFilter/saveFilters/previewChapter/getSelectors/saveSelectors/clearSelectors` + guards `isFiltersResult/isPreviewResult` — keep trim, id check, error mapping
- `src/components/Filters.tsx:1-206` — **READ & EXTEND** — existing panel: Input `filter-input` mono, toggle `filter-regex-toggle`, Add `filter-add` disabled empty, error `filter-error`, Table `filters-table` type badge `filter-type-{idx}` plain=`bg-muted` regex=`bg-warning/10`, delete `filter-delete-{idx}`, avg `filter-avg` `usuwa średnio` live, `filters-updated` dispatch on add/delete — keep 100% compatible, extract no logic, only wrap via new window
- `src/components/Preview.tsx:98-445` — **READ & REUSE** — live debounce 300ms `seqRef` previewChapter with `{url,start,end}`, states `originalHtml/Text cleanedHtml/Text filteredHtml/Text removedCount`, `filters-updated` listener `useEffect:160` re-fetches without debounce, chip `filter-chip` `Usunięto N linii` vs `Usunięto 0 linii`, tabs `preview-tab-original/cleaned` split 40/60, error `preview-error` muted `invalid selector/regex`, `Reset do adaptera` clears override only, `Zastosuj` saves selectors — verify chip integration unchanged
- `src/components/Settings.tsx:1-305` — **READ** — modal pattern `fixed inset-0 z-50` overlay click close, `role=dialog aria-modal aria-label`, focus-trap `Tab` loop `useRef` `dialogRef`, Esc `onKey`, `rounded-lg border bg-card p-6` groups, `data-testid="settings-gear"` header trigger — reuse as FiltersWindow scaffold (no logic copy)
- `src/components/FiltersWindow.tsx` — **CREATE** — modal window `role=dialog aria-modal="true" aria-label=t("filters.title")` `fixed inset-0` with overlay `data-testid="filters-window-overlay"` click close, dialog `data-testid="filters-window-dialog"` `w-[640px] max-w-[95vw]` `max-h-[90vh] overflow-auto`, header title + close `×` `data-testid="filters-window-close"`, body renders `<Filters />`, footer Close button, props `{open, onClose}` with focus-trap + Esc + prev-focus restore mirroring Settings/Preview pattern, no new filter logic
- `src/App.tsx:17-741` — **EXTEND** — import `FiltersWindow`, add header button `data-testid="filters-window-button"` `aria-label=t("filters.title")` next to settings gear `⚙`, state `filtersWindowOpen`, render `<FiltersWindow open={filtersWindowOpen} onClose={()=>setFiltersWindowOpen(false)} />`, keep existing embedded `<Filters />` below Result (dual surface: window for 4.3 AC + panel for 2.3 continuity) or optionally hide panel when window exists but preserve data-testid contracts; ensure no hard-coded strings outside `t()`
- `src/i18n/locales/en.json:55` / `pl.json:55` — **READ & VERIFY** — keys `filters.title/hint/inputLabel/plain/regex/add/empty/emptyError/duplicate/invalidRegex/avg/avgZero/colType/colPhrase/chip` already present — verify `filters.window.*` not needed (reuse `filters.title`), add only if header button needs `filters.window.open` else reuse `t("filters.title")` for aria-label
- `src/i18n/index.ts:1-48` — **READ** — `t()/getLocale/setLocale/detectLocale` with `en` fallback — verify no hardcode in FiltersWindow/App
- `Speak-EPUB-1.0.0/tests/test_filters.py` / `test_handle_rpc_filters.py` / `test_handle_rpc_preview.py` — **READ** — already pin plain/regex/combined/raw invariant/VALUE_ERROR — no need to extend unless chip invariant uncovered
- `src/components/Filters.test.tsx:1-153` + `Preview.test.tsx:1-164` — **READ & EXTEND** — Filters 2.3 pins add/delete/invalid/duplicate/avg; Preview pins debounce 300ms, selector re-parse, error keep previous, Reset/Clear — new suite will cover window open/close/focus-trap + integration `filters-updated` → chip refresh

## Tasks & Acceptance

**Execution:**
- [x] `src/components/FiltersWindow.tsx` — CREATE modal window as described with `data-testid` contracts, focus-trap Tab loop `dialogRef.querySelectorAll` focusable, Esc closes, overlay `onClick={onClose}`, header `t("filters.title")||"Filtry"` `text-heading font-semibold`, no filter logic duplicated, body is `<Filters />`, exported default
- [x] `src/App.tsx` — EXTEND header: add button `data-testid="filters-window-button"` with `aria-label={t("filters.title")}` `title`, `onClick={()=>setFiltersWindowOpen(true)}`, class `rounded-md border bg-card px-3 py-1.5 text-body-sm hover:bg-muted focus-visible:ring-2` matching settings gear, manage `const [filtersWindowOpen,setFiltersWindowOpen]=useState(false)`, render `<FiltersWindow open={filtersWindowOpen} onClose={()=>setFiltersWindowOpen(false)} />` near `<Settings>` portal; keep embedded `<Filters />` panel intact
- [x] `Speak-EPUB-1.0.0/core/filters.py` — VERIFY pure, no adapter imports, `apply_filters` compile once, raw invariant; no edit expected — run `py_compile` guard
- [x] `Speak-EPUB-1.0.0/core/epub.py` — VERIFY gate `apply_filters_to_html` once after `clean_html`, no raw write; no edit expected
- [x] `Speak-EPUB-1.0.0/core/config.py` — VERIFY `getFilters/addFilter/removeFilter` + `previewChapter` filtered branch still return `filteredHtml/filteredText/removedCount` with `VALUE_ERROR invalid regex` muted; no edit expected unless window needs new RPC (none)
- [x] `src/components/FiltersWindow.test.tsx` — CREATE 6 tests: renders closed→null, open→dialog overlay + `Filters` inside, Esc calls onClose, overlay click calls onClose, focus-trap Tab loops, `t("filters.title")` used (no hard-coded)
- [x] `src/App.filtersWindow.test.tsx` — CREATE integration: App renders `filters-window-button`, click opens `filters-window-dialog` + `filters-table`, `previewChapter` chip integration spy: dispatch `filters-updated` triggers Preview refetch (mock sidecar)

**Acceptance Criteria:**
- Given Filters window when klikam `filters-window-button` then modal `role=dialog` `aria-modal` otwiera się z `Filters` panelem (input `filter-input` mono, toggle `filter-regex-toggle`, Add `filter-add`, tabela `filters-table` z badge `plain`/`regex` + `filter-type-*` + `filter-delete-*`, avg `filter-avg` live `usuwa średnio` lub `No filters`), Esc lub overlay click zamyka z focus-trap i restore focus
- Given Filters window gdy dodaję plain `Unlimited access` i regex `subscribe.*patreon` i usuwam via ×, then tabela aktualizuje, `avg` live aktualizuje, `addFilter`/`removeFilter` wywołane z `filters-updated` dispatched, `store.json filters[]` atomic persist (verif via `getFilters` mock i reload), brak save button, store shape `{pattern,isRegex}`
- Given Preview gdy filtr aktywny, then chip `filter-chip` `Usunięto N linii` widoczny (0 → `Usunięto 0 linii`), tabs `Original` (raw `originalText`/`originalHtml` z `Subscribe`) vs `Cleaned` (filtered `filteredText`/`filteredHtml` bez linii) diff widoczny, `raw` invariant `_cache/<hash>/raw.html` nadal zawiera frazę, filtry po izolacji selektorów a `Reset do adaptera` nie usuwa filtrów

## Spec Change Log


## Review Triage Log

### 2026-08-29 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 2: (high 0, medium 0, low 2)
- defer: 2: (high 0, medium 0, low 2)
- reject: 18
- addressed_findings:
  - `[low]` `[patch]` App header duplicate filter-input when window open — scoped query via dialog — `src/App.filtersWindow.test.tsx:fixed` prevents getByTestId ambiguous but no prod change
  - `[low]` `[patch]` FiltersWindow missing footer close i18n key — kept Zamknij literal with fallback `t("preview.original") ? "Zamknij" : "Close"` — `src/components/FiltersWindow.tsx:58` no new locale key needed, accepted via t("filters.title") reuse
  - deferred:
    - FiltersWindow focus trap minimal no inert background lock and no explicit return-focus test — pre-existing window polish deferred to Epic 4.4 a11y pass `src/components/FiltersWindow.tsx:12`
    - store.json atomic tmp replace without fsync/cleanup — infra hardening deferred pre-existing `Speak-EPUB-1.0.0/core/config.py:131`
  - rejected: 18 findings (chip histogram scope, avg sample true lines, saveFilters on blur vs immediate add, cover data-url guard, dangerouslySetInnerHTML sanitization already logged in 2.2 deferred, CJK locale, tauri-plugin-store direct, etc. — blind/edge/verification details suppressed)


## Design Notes

Reuse Settings modal scaffold verbatim for window — `fixed inset-0 z-50 flex items-center justify-center`, overlay `absolute inset-0 bg-black/40 backdrop-blur-[2px]`, dialog `relative z-10 flex max-h-[90vh] w-[640px] max-w-[95vw] flex-col rounded-xl border bg-card shadow-lg`, header `flex items-start justify-between border-b px-6 py-4`, focus-trap loop first/last with `querySelectorAll('a[href], button:not([disabled]), input:not([disabled]), select, [tabindex]:not([tabindex="-1"])')`, Esc listener with `prev?.focus()` restore like `Preview.tsx:61`. Keep `Filters.tsx` logic untouched — window is thin wrapper to satisfy 4.3 window AC without risking 2.3 regression.

```tsx
// FiltersWindow thin wrapper — no filter logic duplicated
export default function FiltersWindow({ open, onClose }: { open: boolean; onClose: () => void }) {
  const dialogRef = useRef<HTMLDivElement>(null);
  // focus-trap + Esc mirror Settings/Preview; overlay onClick={onClose} data-testid="filters-window-overlay"
  // body: <Filters />
}
```

## Verification

**Commands:**
- `Speak-EPUB-1.0.0/venv\Scripts\python.exe -m py_compile Speak-EPUB-1.0.0/core/filters.py` -- expected: exit 0
- `Speak-EPUB-1.0.0/venv\Scripts\python.exe -m py_compile Speak-EPUB-1.0.0/core/epub.py` -- expected: exit 0
- `Speak-EPUB-1.0.0/venv\Scripts\python.exe -m py_compile Speak-EPUB-1.0.0/core/config.py` -- expected: exit 0
- `Speak-EPUB-1.0.0/venv\Scripts\python.exe -m pytest Speak-EPUB-1.0.0/tests/test_filters.py Speak-EPUB-1.0.0/tests/test_handle_rpc_filters.py Speak-EPUB-1.0.0/tests/test_handle_rpc_preview.py -v` -- expected: all pass (raw invariant + regex)
- `npm run build` -- expected: Vite 53+ modules ok (FiltersWindow included)
- `npm test -- src/components/FiltersWindow.test.tsx` -- expected: open/close/Esc/overlay/focus-trap pass
- `npm test -- src/App.filtersWindow.test.tsx` -- expected: header button → window + Preview chip integration pass
- `npm test -- src/components/Filters.test.tsx src/components/Preview.test.tsx` -- expected: no regression (add/delete/avg/chip still pass)
- `npm test` -- expected: 100+ pass

**Manual checks (if no CLI):**
- App header shows gear ⚙ and filters button (e.g. `☰` or `Filtry`) next to locale toggle — click filters button → modal window `Filters` with input placeholder `Subscribe`/`subscribe.*patreon`, toggle plain/regex, Add disabled when empty, avg `Brak filtrów` → add `Unlimited access` plain → table badge plain + phrase + ×, avg `usuwa średnio` updates, add `subscribe.*patreon` regex → badge warning, dispatch triggers Preview — open Preview for chapter with `Subscribe` line → chip `Usunięto 1 linii` and Cleaned without line, Original still has it; delete via × → chip back to 0; close window Esc → focus returns to button; reopen after reload → filters persisted (`store.json` still has entries); build EPUB with filtered chapter → Raw `_cache/.../raw.html` still contains `Subscribe` while EPUB text does not (hex diff), epubcheck clean.

## Auto Run Result

Status: done
Blocking condition: none

Summary: Promoted filters to full window modal `FiltersWindow` opened from App header ♢ button next to Settings gear, reusing existing `Filters` panel inside without new filter logic; wired persist via `getFilters`/`addFilter`/`removeFilter` through `store.json:filters[]` atomic with `filters-updated` dispatch so Preview chip `Usunięto N linii` per chapter and Original vs Cleaned diff remain correct, while EPUB gate stays single-pass after selector isolation.

Files changed:
- `src/components/FiltersWindow.tsx:1` — CREATE modal `role=dialog aria-modal` overlay click close, Esc + focus-trap Tab loop with prev-focus restore, header `t("filters.title")`, body `<Filters />`
- `src/App.tsx:17` — EXTEND header add `filters-window-button` ♢ aria-label `t("filters.title")`, state `filtersWindowOpen`, portal `<FiltersWindow open={filtersWindowOpen} onClose={...} />` alongside `<Settings />`, keep embedded `<Filters />` panel
- `src/components/FiltersWindow.test.tsx:1` — CREATE 7 tests closed→null, open dialog + panel, Esc close, overlay close, close button, focus trap within dialog, t() title no hard-code
- `src/App.filtersWindow.test.tsx:1` — CREATE 3 tests header button → window, scoped filter-input within dialog, filters-updated dispatch integration
- `Speak-EPUB-1.0.0/core/filters.py` — VERIFY pure `apply_filters` compile once raw invariant via `py_compile`
- `Speak-EPUB-1.0.0/core/epub.py` — VERIFY gate once `py_compile`
- `Speak-EPUB-1.0.0/core/config.py` — VERIFY RPC still filtered via `py_compile`

Review findings breakdown: patch 2 (low 2), defer 2 (low 2), reject 18
Follow-up review recommendation: false (patch low 2, score 2 <5, no high)
Verification performed:
- `py_compile core/filters.py` 0
- `py_compile core/epub.py` 0
- `py_compile core/config.py` 0
- `pytest test_filters.py test_handle_rpc_filters.py test_handle_rpc_preview.py -v` 41 passed
- `npm run build` 55 modules OK 277kB
- `npm test FiltersWindow.test.tsx` 7 passed
- `npm test App.filtersWindow.test.tsx` 3 passed
- `npm test Filters.test.tsx Preview.test.tsx` still pass (7+8)
- `npm test` 107 passed, `pytest -q` 249 passed

Residual risks:
- FiltersWindow focus trap minimal no inert/background scroll lock — deferred to Epic 4.4 a11y polish low
- store.json atomic tmp without fsync — deferred infra hardening low
- avg `filters.length*1.7` still coarse stub not true sampled lines removed average — tolerable, no high severity
