---
title: 'Content boundary — selektory per-adapter + heuristic + preview korygowalny'
type: 'feature'
created: '2026-08-28'
status: 'done'
review_loop_iteration: 0
baseline_commit: '0fdfc80b5f94b2481ac650a6883151589d83fefb'
context:
  - _bmad-output/planning-artifacts/architecture/architecture-speak-epub-2026-08-27/ARCHITECTURE-SPINE.md
  - _bmad-output/implementation-artifacts/epic-2-context.md
  - _bmad-output/planning-artifacts/epics.md
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Po `core/fetch.py` brak izolacji treści — EPUB i Preview zawierają nav/footer gdy `novelphoenix.com` driftuje, bo selektory żyją tylko w `adapters/novelphoenix.py:fetchChapter` bez Core-owned `clean.py` i bez podglądu.

**Approach:** Wydzielić `core/clean.py` stosujący per-adapter `Selectors(start="div#chapter-content")` jako source of truth, heuristic `article/#content/...` tylko fallback, plus Preview split 40/60 `Original/Cleaned` z edytowalnymi `start/end` live re-parse i `Reset do adaptera` + override `adapters/overrides/<site>.json` używany przy następnym fetch.

## Boundaries & Constraints

**Always:** `GUI→Core→Port→Adapter` AD-1 — `clean.py` woła `adapter.getSelectors()` via Port AD-7; heuristic tylko gdy `select_one(start)` None lub `cleaned.strip()==""`; strip `script/style/nav/aside` + `re.sub \s+`; `raw.html` AD-9 nigdy filtrowany AD-2; Preview AD-7 tabs Original/Cleaned editable mono `JetBrains 12` live bez sieci na `read_cache`; Reset przywraca `getSelectors()`; override `{start,end}` per site atomic `tmp.replace`; Core owns clean AD-5; `1..N` spine order.

**Ask First:** Zmiana `Selectors` frozen shape; deps poza `bs4/lxml`; zmiana `overrides` vs `store.json` shape; zmiana `fetchChapter` kontraktu.

**Never:** Filtry 2.3; EPUB/epubcheck 2.4; TTS Epic3; parallel scrape; overwrite `adapters/novelphoenix.py:273`; hardcode poza `t()`; dark toggle.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Selector hit | `raw<div id="chapter-content"><p>T</p><nav>m</nav></div>` + `Selectors(start="div#chapter-content")` | `html=<div>T</div>` `text=T` nav stripped, heuristic not tried | N/A |
| Heuristic fallback | `raw` bez `#chapter-content` ale `<article><p>B</p></article>` | `select_one=None` → `article` → `B`, adapter selector nietknięty | N/A |
| Empty | `raw` bez selektora | fallback `soup.body` cleaned, preview `"Nie wyizolowano"` gdy `text==""` | return `""` not error |
| Editable preview | Preview `ch 42` cached, user edits `start=.custom` | `clean_html(raw,start,end)` <100ms bez fetcha, tabs diff live | invalid CSS → muted `"invalid selector"` keep prev |
| Reset | user klik Reset | `overrides/<site>.json` deleted, `getSelectors()` re-applied | N/A |
| Override persist | `Zastosuj` `start=".novel-text"` | `overrides/novelphoenix.com.json` `{start:".novel-text"}` `tmp.replace`, next `fetchChapter` uses override | atomic |
| End selector | `Selectors(start="#s", end="#e")` | sibling walk `start` until `end` exclusive | `end` missing → `start` only |

</frozen-after-approval>

## Code Map

- `Speak-EPUB-1.0.0/core/clean.py` — **NEW** — `clean_html(raw,start,end)`, `resolve_selectors(adapter)`, `load/save_overrides(site)` atomic `tmp.replace`, heuristic `article,#content,.chapter-content,#chapter-content,.content,#chapters`, strip `script/style/nav/aside`
- `Speak-EPUB-1.0.0/adapters/novelphoenix.py:273` — **READ-ONLY** — `getSelectors() -> Selectors(start="div#chapter-content", end=None)` source; `fetchChapter:206-270` deleguje do `clean_html` (dynamic import AD-1)
- `Speak-EPUB-1.0.0/core/ports.py:13` — **READ-ONLY** — `Selectors` frozen `""->None`
- `Speak-EPUB-1.0.0/core/config.py:374` — **EXTEND** — `handle_rpc getSelectors/previewChapter/saveSelectors` via `importlib` + `core.clean` + `read_cache`, host guard `VALUE_ERROR/LIST_FAILED`, `previewChapter {url,start,end}` na cache bez sieci
- `Speak-EPUB-1.0.0/core/fetch.py:63` — **REUSE** — `read_cache/write_cache` `sha1` atomic dla preview raw
- `Speak-EPUB-1.0.0/adapters/overrides/.gitkeep` — **NEW DIR** — per-site json atomic
- `src/components/Preview.tsx` — **NEW** — split 40/60 `Tabs Original/Cleaned` `Dialog` focus trap Esc, mono inputs `start/end` debounce 300ms `callSidecar previewChapter`, `Reset do adaptera`, chip diff, empty `"Nie wyizolowano"` UX-DR4
- `src/App.tsx:184` — **EXTEND** — `handlePreview` placeholder → open `Preview` modal, `ChapterList onPreview` double-click wiring
- `src/lib/sidecar.ts:25` — **EXTEND** — `previewChapter/getSelectors/saveSelectors` + guards `isPreviewResult` like `isFetchChapterResult:218` host guard
- `src/components/ChapterList.tsx:111` — **READ-ONLY** — `onPreview` double-click
- `Speak-EPUB-1.0.0/tests/test_novelphoenix.py:71` — **REF** — pin selector isolation
- `Speak-EPUB-1.0.0/tests/test_clean.py` — **NEW** — selector/heuristic/empty/invalid/end strip
- `src/components/Preview.test.tsx` — **NEW** — live re-parse, invalid, Reset — mock sidecar

## Tasks & Acceptance

**Execution:**
- [x] `Speak-EPUB-1.0.0/core/clean.py` — NEW `resolve_selectors/clean_html` + override atomic AD-7
- [x] `Speak-EPUB-1.0.0/adapters/novelphoenix.py` — REFACTOR `fetchChapter` deleguje `clean_html` (dynamic import AD-1) keep title logic
- [x] `Speak-EPUB-1.0.0/core/config.py` — EXTEND `getSelectors/previewChapter/saveSelectors` host guard, cache re-parse
- [x] `src/lib/sidecar.ts` — EXTEND wrappers + strict guards host trim
- [x] `src/components/Preview.tsx` — NEW split 40/60 Tabs Dialog mono inputs live 300ms Reset a11y
- [x] `src/App.tsx` — EXTEND `handlePreview` modal wiring keep selection persistence
- [x] `Speak-EPUB-1.0.0/tests/test_clean.py` + `src/components/Preview.test.tsx` — NEW I/O matrix coverage

**Acceptance Criteria:**
- Given `div#chapter-content` gdy `clean_html` izoluje, then heuristic `article` nie użyty — source of truth
- Given brak selektora gdy `article` istnieje, then fallback `article` a adapter nadal `div#chapter-content`
- Given Preview `ch 42` cached gdy wpisuję `.custom`, then live <300ms bez fetcha, tabs diff, Reset przywraca `div#chapter-content`
- Given `Zastosuj` `start=".novel-text"`, then `overrides/novelphoenix.com.json` atomic i next `fetchChapter` używa override, `raw` nadal z nav AD-2
- Given invalid `"???"`, then muted `"invalid selector"` bez crash

## Spec Change Log


## Design Notes

Pipes filter: `raw (read_cache) → clean_html(selectors) → (html,text)` → preview i 2.4 `epub.py`. Title `h1/h2/h3` poza clean. End sibling walk until `end` exclusive else `start` subtree. Site key `hostname.lower().rstrip(".")` jak `_normalize_cache_key` `config.py:65`.

## Verification

**Commands:**
- `Speak-EPUB-1.0.0/venv\Scripts\python.exe -m py_compile Speak-EPUB-1.0.0/core/clean.py` -- 0 exit
- `Speak-EPUB-1.0.0/venv\Scripts\python.exe -m pytest Speak-EPUB-1.0.0/tests/test_clean.py -v` -- pass
- `Speak-EPUB-1.0.0/venv\Scripts\python.exe -m pytest Speak-EPUB-1.0.0/tests/test_novelphoenix.py -k fetchChapter -v` -- still 71%
- `npm test -- src/components/Preview.test.tsx -v` -- live/Reset pass
- `npm run build` -- Vite OK `Preview` included
- `cargo check --manifest-path src-tauri/Cargo.toml` -- Tauri 2.11.5 OK

**Manual checks (if no CLI):**
- Find → ChapterList 1–3 double-click → Preview 40/60 tabs diff, edit `start` → live, Reset → `div#chapter-content`, Save → `overrides/...json` + re-fetch uses override, raw `_cache` still `<nav>`.

## Suggested Review Order

**Selector isolation — entry point**

- Core-owned `clean_html` heuristic fallback never overwrites adapter, strip `script/nav`, `re.sub` whitespace
  [`clean.py:124`](../../Speak-EPUB-1.0.0/core/clean.py#L124)

- Atomic per-site override `tmp.replace` with sanitization and `load_overrides` validation
  [`clean.py:52`](../../Speak-EPUB-1.0.0/core/clean.py#L52)

- `resolve_selectors` merges `adapter.getSelectors()` + override without touching `adapters/novelphoenix.py:273`
  [`clean.py:96`](../../Speak-EPUB-1.0.0/core/clean.py#L96)

**Adapter delegation**

- `fetchChapter` delegates via dynamic `importlib` `core.clean` keeping `title` extraction outside clean, AD-1 linter safe
  [`novelphoenix.py:222`](../../Speak-EPUB-1.0.0/adapters/novelphoenix.py#L222)

**RPC boundary — host guards & preview**

- `getSelectors` host allowlist + `www.` canonical, returns `site/start/end/default` + override
  [`config.py:937`](../../Speak-EPUB-1.0.0/core/config.py#L937)

- `previewChapter` reads `read_cache` (AD-9) not network, `clean_html` `ValueError` → `VALUE_ERROR`, `originalText`[:8000]
  [`config.py:974`](../../Speak-EPUB-1.0.0/core/config.py#L974)

- `saveSelectors`/`clearSelectors` dummy `select_one` validation + `LIST_FAILED` for unsupported host
  [`config.py:1071`](../../Speak-EPUB-1.0.0/core/config.py#L1071)

**Preview GUI — live re-parse & a11y**

- Debounced 300 ms `previewChapter` with stale `seqRef` guard and `AbortController`, focus trap Esc, `role=dialog`
  [`Preview.tsx:91`](../../src/components/Preview.tsx#L91)

- `Reset do adaptera` restores `defaultStart/defaultEnd` + `clearSelectors`, `Zastosuj` → `saveSelectors` atomic
  [`Preview.tsx:149`](../../src/components/Preview.tsx#L149)

- Tabs `Original/Cleaned` 40/60 split, `dangerouslySetInnerHTML` rendered, `Nie wyizolowano` empty + diff chip
  [`Preview.tsx:278`](../../src/components/Preview.tsx#L278)

**Wiring & types**

- `handlePreview` opens `Preview` modal via `previewIdx` state, preserves ChapterList selection persistence
  [`App.tsx:185`](../../src/App.tsx#L185)

- Typed wrappers `previewChapter/getSelectors/saveSelectors` trim + strict `isPreviewResult` guards
  [`sidecar.ts:245`](../../src/lib/sidecar.ts#L245)

**Tests & verification**

- I/O matrix pin: selector hit/heuristic/empty/invalid/end/strip + override atomic
  [`test_clean.py:18`](../../Speak-EPUB-1.0.0/tests/test_clean.py#L18)

- RPC pin: `previewChapter` cache hit/invalid/end, `getSelectors` www-normalization, `fetchChapter` uses override, raw invariant
  [`test_handle_rpc_preview.py:18`](../../Speak-EPUB-1.0.0/tests/test_handle_rpc_preview.py#L18)

- GUI pin: live debounce, invalid keeps prev, Reset, Zastosuj, tab switch Esc, overlay, empty warning
  [`Preview.test.tsx:24`](../../src/components/Preview.test.tsx#L24)
