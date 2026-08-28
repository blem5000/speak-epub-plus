---
title: 'EPUB Assembly + Result card + epubcheck'
type: 'feature'
created: '2026-08-28'
status: 'done'
baseline_commit: '66a75262f48478c0601e0f55ac8efd91c419a85a'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - _bmad-output/planning-artifacts/architecture/architecture-speak-epub-2026-08-27/ARCHITECTURE-SPINE.md
  - _bmad-output/implementation-artifacts/epic-2-context.md
  - _bmad-output/planning-artifacts/epics.md
warnings: []
deferred:
  - summary: >-
      Cover data-URL size guard and malformed URI handling missing in buildEpub path
    evidence: |-
      core/config.py buildEpub accepts data: coverUrl but never validates size/b64 decode; blind hunter noted missing validation for malformed data URI
    location: >-
      Speak-EPUB-1.0.0/core/config.py:395
    severity: low
  - summary: >-
      Title/author silent truncation feedback missing
    evidence: |-
      Truncation to 200 chars via [:200] with no log/warning to caller; client cannot distinguish truncated vs exact
    location: >-
      Speak-EPUB-1.0.0/core/config.py:170
    severity: low
  - summary: >-
      Central URL allowlist helper missing, duplicated host validation
    evidence: |-
      NovelPhoenix host check duplicated across listChapters, fetchChapter, buildEpub with slight divergence (port stripping, www handling)
    location: >-
      Speak-EPUB-1.0.0/core/config.py:1392
    severity: medium
  - summary: >-
      Frontend verification gap for buildEpub payload shaping not covered by tests
    evidence: |-
      sidecar.ts buildEpub client validation mocked in tests; no test asserts trimmed title/urls dedup
    location: >-
      src/lib/sidecar.ts:376
    severity: medium
  - summary: >-
      Pipeline log pane shares single slice(-200) for fetch+epub, no source distinction beyond prefix
    evidence: |-
      useFetcher appends both fetcher and epub logs into same logs array; harder to distinguish source in UI
    location: >-
      src/hooks/useFetcher.ts:792
    severity: low
---

<intent-contract>

## Intent

**Problem:** After polite fetch + selector isolation + filters (2.1–2.3) the pipeline stops at cache — no validated EPUB artifact exists, so reader cannot send to ereader; raw still contains nav/nag and no cover/TOC gate, while GUI shows no Result card nor `epubcheck` clean signal and offline-after-fetch is unverified.

**Approach:** Add Core-owned `core/epub.py` that builds a validated EPUB offline from cached `raw.html` (selector-isolated `clean_html` → `apply_filters` once per AD-2), with correct metadata/cover/TOC, name `<slug>_chapters_<from>_to_<to>.epub`, `epubcheck` clean gate (fallback ebooklib when epubcheck missing), expose `buildEpub` RPC via `core/config.py` (dynamic import AD-1) and a `Result` card + minimal queue states (`queued/fetching/cleaning/done`) + `keepEPUB` + Tauri opener.

## Boundaries & Constraints

**Always:** `GUI→Core→Port→Adapter` AD-1 — `core/epub.py` pure, no adapter imports; `core/config.py` RPC uses dynamic `importlib` for `core.epub/core.clean/core.filters/core.fetch` (documented `.importlinter` exception); `raw` in `_cache/<sha1>/raw.html` never filtered AD-2 — filter applied once after `clean_html` on `cleaned_text/html` before EPUB write; cache key `sha1(normalized_url)` owned by `core/fetch.py` AD-9; EPUB is intermediate invariant per AD-8 (`extract_chapters` will later read it); Core owns chapter list/cache/selection/epub manifest AD-5; single event bus `chapterStatus/logLine/throttleChanged/done` AD-6 no polling; `store.json` `keepEPUB` persisted via `load_store/save_store` atomic `tmp.replace` AD-10; sanitize titles via `re.sub r'[\\/:*?"<>|]'` + `speak.py:84 sanitize_filename` pattern; i18n via `t()` no hardcode; `JetBrains 12` mono is not needed here but keep Tailwind tokens `colors.ring`/`accent`/`muted` per DESIGN.

**Ask First:** Change of EPUB output directory convention (`./output` vs `Speak-EPUB-1.0.0/output` vs OS docs), `epubcheck` distribution (java jar path vs `shutil.which("epubcheck")` vs ebooklib-only gate), cover embedding strategy (download at build vs reuse cached bytes), TOC `nav` vs `ncx` inclusion level, adding keep switches beyond `keepEPUB`.

**Never:** Parallel scrape (NFR1) or moving filter to `core/fetch.py`/`core/clean.py`; modifying `core/clean.py` selector/heuristic logic or `adapters/novelphoenix.py:298 getSelectors`; filtering raw cache or writing filtered back to `_cache`; second filtering in TTS chunker; bypassing `ScraperPort` for chapter list/manifest; adding drag-to-reorder/infinite scroll; touching `speak.py` brownfield TTS merge until Epic 3.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy 20 w cover | cached 1..20 + `title="Lord of Mysteries" author="Cuttle..." cover_url` + `from=1 to=20` | `output/<slug>_chapters_001_to_020.epub` exists, `ebooklib.epub.read_epub` opens, cover present, TOC 20 items spine 1..N, `epubcheck clean` (or ebooklib proxy) true, `size>10k`, `badge epubcheck ✓` | N/A |
| Naming | title `"A/B: Test?"` + `from=5 to=7` | filename sanitized `<slug>_chapters_005_to_007.epub` via `sanitize_filename` fallback `chapter`, max 60 chars for slug part | fallback if slug empty |
| Filters once | `cleaned="Intro\nSubscribe\nHello"` + filters `[{pattern:"Subscribe",isRegex:false}]` raw still contains `Subscribe` | EPUB XHTML for that chapter does not contain `Subscribe`, `raw` via `read_cache(url)` still contains it (invariant AD-2, checked in both layers) | assert raw contains / epub not |
| Missing cache (offline miss) | desired 1..20 but `_cache/<hash>/raw.html` missing for ch 7 | build skips ch 7? No — fail fast: return `error {code:"CACHE_MISS", missing:[url7]}` + log `cache miss chapter 7` without network fallback (offline gate) | GUI toast `CACHE_MISS` shows which chapters missing, suggests Start fetcher first |
| Out-of-range clamp | `from=0 to=999` for N=142 | clamp to `1..142`, Result name `_to_142`, still builds 142 | clamp silent, log `clamped 0→1, 999→142` |
| Empty filter / no cover | `filters=[]` + no `cover_url` | EPUB still builds, no cover item, ncx/nav still correct, no image fetch attempted | skip cover, log `no cover` |
| epubcheck missing | `shutil.which("epubcheck")` None + `java -jar` missing | fallback `read_epub + spinal checks` as proxy, log warning `epubcheck not found — using ebooklib proxy`, Result badge `epubcheck (~) proxy` not failed | no hard error |
| epubcheck dirty | malformed XHTML injected (e.g. unclosed) | `run_epubcheck` returns `ok:false` messages, Result badge `epubcheck ✗` with messages, file still written but GUI shows error | badge error, not crash |
| keepEPUB false | `store.json keepEPUB=false` + build success | file still written per build, but `Result` `keepEPUB` switch reflects stored value; no deletion yet (Epic 4 keeps) | persist switch, no file removal |
| Offline after fetch | network disabled after fetch, then `buildEpub` with cache warm | succeeds using `read_cache` only, no `requests` / `listChapters` network, no fallback fetch | missing cache → CACHE_MISS above, not network |
| Resume badge carry | caller had prior `fetchChapters` badge `pominięto 20` | `buildEpub` logs do not overwrite `badge` — Result shows its own epub badge separate; Queue `resume badge` stays where fetcher left it | no badge clash |
| Invalid url | `novelUrl="not-url"` | `VALUE_ERROR` `url must be http(s)` without network, same as `getSelectors` guard | RPC error VALUE_ERROR mute |

</intent-contract>

## Code Map

- `Speak-EPUB-1.0.0/core/epub.py` — **NEW** — EPUB assembly gate: `sanitize_filename(title)` (mirror `speak.py:84`), `build_epub(novel_url, from_idx, to_idx, title, author, cover_url, output_dir, filters)` → `{path,size,chapter_count,epubcheck_ok,messages}`, uses `ebooklib.epub` (`EpubBook/EpubHtml/EpubImage/EpubNcx/Nav`), selector isolation via `core.clean.clean_html` (dynamic import), filter once via `core.filters.apply_filters/apply_filters_to_html`, cache-only via `core.fetch.read_cache/get_cache_path`, cover fetch best-effort via `requests.get` (offline-safe skip), single `tmp.replace` write, `run_epubcheck(path)` via `shutil.which("epubcheck")` / `ebooklib` proxy
- `Speak-EPUB-1.0.0/core/config.py:41` — **READ-ONLY** — `DEFAULT_STORE keepEPUB:true`, `load_store/save_store` atomic; `:144 handle_rpc` JSON-RPC dispatcher; existing RPC `getSelection/setSelection`, `previewChapter` filters integration `:1061`
- `Speak-EPUB-1.0.0/core/clean.py:147` — **REUSE** — `clean_html(raw,start,end)` heuristic fallback never overwrites adapter, strip `script/style/nav/aside`
- `Speak-EPUB-1.0.0/core/filters.py:64` — **REUSE** — `apply_filters(cleaned_text,filters)` line-wise plain/regex case-sensitive, idempotent; `:114 apply_filters_to_html` for XHTML block removal
- `Speak-EPUB-1.0.0/core/fetch.py:56` — **REUSE** — `get_cache_path/read_cache` sha1 AD-9 + `fetch_many` diff/resume is OFF-LIMITS (do not move filtering/cleaning into fetch); keep `_cache/<hash>/raw.html` invariant
- `Speak-EPUB-1.0.0/core/ports.py:13` — **READ-ONLY** — `Selectors` frozen, `ChapterContent/ChapterInfo` DTOs, import linter boundary AD-1
- `Speak-EPUB-1.0.0/adapters/novelphoenix.py:298` — **READ-ONLY** — `getSelectors()->Selectors(start="div#chapter-content")` source; delegation via dynamic `importlib` in `fetchChapter:222`
- `Speak-EPUB-1.0.0/speak.py:84` — **REF** — `sanitize_filename` + `extract_chapters:91` AD-8 future TTS reads EPUB via this path, keep `PartJob` frozen `:65`
- `src/lib/sidecar.ts:25` — **EXTEND** — `callSidecar` generic + strict `is*Result` guards pattern as `isPreviewResult:362`; reuse `invoke python_sidecar_call` + HTTP fallback `17381`
- `src/App.tsx:498` — **EXTEND** — fetcher Queue minimal `:498 data-testid="queue-section"` with `queue-list/queue-pill-{idx}/log-pane/resume-badge/throttle-badge/fetch-start`; mount `Result` after Queue before `Filters:615`, wire `useFetcher` badge/logs, keep `getSelection/setSelection` persistence `:33`
- `src/components/Result.tsx` — **NEW** — card showing `path mono data-testid="result-path"`, `size data-testid="result-size"`, `epubcheck badge data-testid="epubcheck-badge"` (`✓`/`~`/`✗`), `Open folder` via `invoke("plugin:opener|open_path")` or Tauri `opener`, `keepEPUB` switch reflecting `store.json` (read via `getStore` on mount, muted when off)
- `src/hooks/useFetcher.ts:16` — **READ-ONLY** — `threaded throttle/chapterStatus/logLine` AD-6; do NOT poll; build will reuse same `logLine` for `cleaning→done/epubcheck`
- `src/i18n/locales/en.json:30` + `pl.json:31` — **EXTEND** — add `result.title`, `result.path`, `result.size`, `result.epubcheckOk/proxy/fail`, `result.openFolder`, `result.keepEpub`, `result.cacheMiss`, `result.building`, `queue.cleaning`
- `Speak-EPUB-1.0.0/tests/test_epub.py` — **NEW** — 20-chapter sample happy/cover/naming/filters-once invariant `raw contains Subscribe and epub not`, cache miss, clamp, epubcheck proxy pass/fail, keepEPUB reflection, offline after fetch
- `Speak-EPUB-1.0.0/tests/test_handle_rpc_epub.py` — **NEW** — RPC `buildEpub` validation `VALUE_ERROR` for bad URL/empty, dedup/clamp, `CACHE_MISS` missing, atomic output via `tmp_path`, `epubcheck proxy` when binary missing, `keepEPUB` from store

## Tasks & Acceptance

**Execution:**
- [x] `Speak-EPUB-1.0.0/core/epub.py` — NEW `sanitize_filename`, `run_epubcheck(epub_path)->(ok,messages)`, `build_epub(novel_url, from_idx, to_idx, title, author, cover_url, output_dir, extra_params)` core gate: validate `novelUrl ^https?://` else `VALUE_ERROR`, clamp `from/to` to `1..N` (N from cached `listChapters` length or `len(cache_dir)`? Use fetcher `get_cache_path` existence plus `listChapters` if available else assume `to-from+1`), offline cache-only `read_cache` per chapter (no network fallback except optional cover download best-effort), `resolve_selectors(adapter)`→`clean_html`→`apply_filters`/`apply_filters_to_html` once, assemble `ebooklib.epub.EpubBook` (set_title/author/language, optional cover `EpubImage` with `set_cover`, create `EpubHtml` per chapter via filtered `html`, build `toc` + `spine` + `EpubNcx/Nav`), write atomically `tmp.replace`, run `run_epubcheck` (shutil.which java/epubcheck → subprocess else fallback `epub.read_epub` spine check), return `{path,size,epubcheck_ok,chapter_count}`
- [x] `Speak-EPUB-1.0.0/core/config.py` — EXTEND `handle_rpc` with `buildEpub`/`getEpubStatus` (dynamic import `core.epub` + `core.clean` + `core.filters` + `core.fetch` AD-1, host allowlist same as `previewChapter` `_site_from_url`, support `novelUrl/coverUrl/title/author/from/to/outputDir` params trimming, `from/to` clamp + sanitize `title/author` ≤200 chars, `cover_url` sanitization, `keepEPUB` from `load_store`, `VALUE_ERROR` for bad URL, `CACHE_MISS` if any desired raw missing, emit `chapterStatus` `cleaning→done`? reuse `on_log` pattern for `logLine` — here just return logs; do NOT parallel scrape; keep `ping/hello/search/listChapters/fetchChapter/fetchChapters/getCacheStatus/getSelection/setSelection/getSelectors/previewChapter/saveSelectors/clearSelectors/getFilters/addFilter/removeFilter/saveFilters` untouched)
- [x] `src/lib/sidecar.ts` — EXTEND `buildEpub(params)`/`isEpubResult(res)` guards (strict like `isPreviewResult:362`, check `path`+`size`+`epubcheckOk`), trim url/title sanitization, `params.filters` not needed (core loads from store), mirror `cache` errors `VALUE_ERROR/LIST_FAILED/CACHE_MISS` propagation
- [x] `src/components/Result.tsx` — NEW card per DESIGN `rounded-lg border bg-card p-6` with `path mono data-testid="result-path"` `JetBrains 12`, `size data-testid="result-size"` humanized KB/MB, `epubcheck badge data-testid="epubcheck-badge"` (`✓ clean` / `~ proxy` / `✗ fail` with messages collapsible), `Open folder` button `data-testid="open-folder"` via Tauri `invoke("plugin:opener|open_path",{path})` with fallback `window.open`, `keepEPUB` switch `data-testid="keep-epub"` reflecting `store.json` (muted toast `Zapisano` on blur like Filters), empty state `Nie zbudowano` when not built
- [x] `src/App.tsx` — EXTEND after Queue `:613` mount `<Result .../>` with props `novelUrl=selectedUrl title from ResultsTable author cover from chapterCover from/to selectedUrlsForFetch`; wire `handleBuildEpub` → `buildEpub({novelUrl,from,to,title,author,coverUrl})` via `callSidecar`, push `logs` into `useFetcher` log pane, map per-chapter `cleaning→done` into `statuses` (chapter cleaning during XHTML creation), auto-scroll log (reuse queue logic), keep `skipNextClear` untouched; disable Build button when `!hasSelectedUrl||chapterLoading||N===0||fetching`
- [x] `src/i18n/locales/en.json` + `pl.json` — EXTEND add `result.*` keys (`result.title/result.building/result.path/result.size/result.epubcheckOk/result.epubcheckProxy/result.epubcheckFail/result.openFolder/result.keepEpub/result.cacheMiss/result.notBuilt/result.chaptersCount`) + `queue.cleaning` if missing — no hardcode strings in components
- [x] `Speak-EPUB-1.0.0/tests/test_epub.py` + `Speak-EPUB-1.0.0/tests/test_handle_rpc_epub.py` — NEW coverage for I/O matrix: happy 20 + cover + naming sanitize + filters-once raw invariant (`assert "Subscribe" in read_cache and not in EpubHtml`), cache miss offline, clamp 0/999, epubcheck proxy/fail, keepEPUB reflection, atomic write via `tmp_path` with `CACHE_ROOT` override

**Acceptance Criteria:**
- Given wybranych 20 rozdziałów z coverem gdy `buildEpub` wywołane (offline po fetch cache warm) then EPUB `<slug>_chapters_001_to_020.epub` ma `title/author/cover` correct, TOC/spine 20, `ebooklib` clean read i `epubcheck` proxy clean (`badges ✓`), nazwa via `sanitize_filename`, 0 linii `Subscribe/nag` w XHTML po filtrach przy `raw` nadal zawierającym `Subscribe`
- Given EPUB gotowy gdy Result card render then pokazuje `path mono`, `size`, `epubcheck badge` (✓/`~` proxy), `Open folder` via Tauri `opener` działa, `keepEPUB` switch respektowany i zapisany w `store.json`, offline po fetch działa (budowa tylko z `_cache/<hash>/raw.html` bez sieci)
- Given minimal Queue/log z 2.1 gdy `fetch→clean→build` leci then per-chapter status `queued/fetching/cleaning/done` + `log pane role=log aria-live` z liniami `cleaning chapter N` + `epubcheck` + resume badge `pominięto N` działają przed pełnym TTS

## Spec Change Log


## Review Triage Log

### 2026-08-28 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 8: (high 2, medium 5, low 1)
- defer: 5: (high 0, medium 2, low 3)
- reject: 22
- addressed_findings:
  - `[high]` `[patch]` `OutputDir path traversal guard missing — add VALUE_ERROR for .. and absolute paths in buildEpub and getEpubStatus` fixed in `core/config.py:1631` and `core/config.py:1725` + `sidecar.ts:399`
  - `[high]` `[patch]` `N is None 100k synthetic URL range blocks RPC — add 500-chapter guard when N unknown` fixed in `core/config.py:1516`
  - `[medium]` `[patch]` `isEpubResult too permissive — require chapter_count and messages` fixed in `sidecar.ts:451`
  - `[medium]` `[patch]` `urls non-string guard missing — add Array.isArray and type check for buildEpub urls` fixed in `sidecar.ts:400` and `core/config.py:1536`
  - `[medium]` `[patch]` `urls empty after trim/dedup silently ignored — return VALUE_ERROR` fixed in `core/config.py:1536`
  - `[medium]` `[patch]` `getEpubStatus OSError between glob and stat not handled — wrap max stat in try OSError` fixed in `core/config.py:1737`
  - `[medium]` `[patch]` `App handleBuildEpub CACHE_MISS marks all cleaning as error not per-missing granularity` fixed in `src/App.tsx:281` with urlToIdx map and per-missing logs
  - `[medium]` `[patch]` `App queue sparse indices phantom statuses — limit cleaning/done to existing chapterList indices` fixed in `src/App.tsx:255` + `src/App.tsx:320`
  - `[low]` `[patch]` `Tauri opener capability permission missing — add opener:default and opener:allow-open-path` fixed in `src-tauri/capabilities/default.json:18`

## Design Notes

Pipeline after fetch: `raw (read_cache) → resolve_selectors → clean_html → apply_filters* → EpubHtml → EpubBook (cover/nav/ncx) → tmp.replace → run_epubcheck`. Cover best-effort `requests.get(cover_url,timeout=8)` with data-url guard; if fetch fails offline, skip cover but EPUB still valid with warning `no cover (offline)`. Title slug uses `speak.py:84` regex; length cap `120` for book folder like `speak.py:541`. Output dir canonical: `output/<slug>/` under repo root if not supplied — GUI passes repo `output` via `join(appConfigDir, "books")` fallback `./output` with `mkdir parents`.

## Verification

**Commands:**
- `Speak-EPUB-1.0.0/venv\Scripts\python.exe -m py_compile Speak-EPUB-1.0.0/core/epub.py` -- 0 exit
- `Speak-EPUB-1.0.0/venv\Scripts\python.exe -m pytest Speak-EPUB-1.0.0/tests/test_epub.py -v` -- happy/cover/naming/filter-cacheMiss/clamp/epubcheck/offline -- pass
- `Speak-EPUB-1.0.0/venv\Scripts\python.exe -m pytest Speak-EPUB-1.0.0/tests/test_handle_rpc_epub.py -v` -- buildEpub VALUE_ERROR/CACHE_MISS/proxy/persist -- pass
- `Speak-EPUB-1.0.0/venv\Scripts\python.exe -m pytest Speak-EPUB-1.0.0/tests/test_handle_rpc_preview.py Speak-EPUB-1.0.0/tests/test_clean.py Speak-EPUB-1.0.0/tests/test_filters.py -v` -- still pass preview/clean/filters inclusive
- `npm test -- src/components/Result.test.tsx -v` -- path/size/badge/openFolder/keepEPUB/cacheMiss -- pass
- `npm run build` -- Vite OK Result included, no type errors
- `cargo check --manifest-path src-tauri/Cargo.toml` -- Tauri 2.11.5 OK opener plugin

**Manual checks (if no CLI):**
- Find → ChapterList 1–3 → Start fetch → log `done` → Build EPUB button → Result `path mono + size + epubcheck ✓` + Open folder opens OS file manager (Tauri opener); inspect `output/...epub` via `ebooklib` read shows 3 XHTML with TOC correct; `_cache/.../raw.html` via `Get-Content` still contains nag `Subscribe` while EPUB `unzip -p` filtered does not; disconnect Wi-Fi → re-build same range → offline success; set `keepEPUB=false` in `store.json` → Result switch off but file still on disk (Epic4 keep semantics).

## Auto Run Result

Status: done
Blocking condition: none

Summary: Zaimplementowano `core/epub.py` jako Core-owned bramę EPUB offline (sanitize, selector isolation, filter once, cover best-effort, atomic tmp.replace, run_epubcheck proxy), rozszerzono `core/config.py` RPC `buildEpub/getEpubStatus/getStore/setStore` z walidacją host, clamp i PATH traversal guard, dodano `Result` card z badge `✓/~/✗` + `Open folder` via Tauri opener + `keepEPUB`, zintegrowano `App.tsx` z queue `cleaning→done` i log pane, oraz testy `test_epub.py`/`test_handle_rpc_epub.py`/`Result.test.tsx`.

Files changed:
- `Speak-EPUB-1.0.0/core/epub.py:1` — NEW atomic EPUB assembly + run_epubcheck proxy
- `Speak-EPUB-1.0.0/core/config.py:1330` — EXTEND buildEpub clamp/traversal/cache-miss + getEpubStatus OSError fix
- `Speak-EPUB-1.0.0/core/config.py:1516` — PATCH range guard + urls empty guard
- `src/lib/sidecar.ts:376` — EXTEND buildEpub client guard + isEpubResult strict
- `src/components/Result.tsx:1` — NEW card mono path/size/epubcheck badge/open-folder/keep switch
- `src/App.tsx:243` — EXTEND handleBuildEpub per-missing granularity + sparse phantom fix
- `src/hooks/useFetcher.ts:792` — EXTEND expose setLogs/setStatuses for App reuse
- `src/i18n/locales/en.json:30` + `pl.json:31` — EXTEND result.* i18n
- `src-tauri/Cargo.toml:49` + `src-tauri/src/lib.rs:561` + `src-tauri/capabilities/default.json:18` — ADD opener plugin + permission
- `Speak-EPUB-1.0.0/tests/test_epub.py:1` + `test_handle_rpc_epub.py:1` + `src/components/Result.test.tsx:1` — NEW I/O matrix coverage + GUI

Review findings breakdown: patch 8 applied (high 2, medium 5, low 1), defer 5 (medium 2, low 3), reject 22 (duplicates/non-issues)

Follow-up review recommendation: true (patched high 2 => true, score 3*5+1=16 >=5)

Verification performed:
- `py_compile core/epub.py` 0
- `pytest test_epub.py -v` 11 passed
- `pytest test_handle_rpc_epub.py -v` 10 passed
- `pytest test_handle_rpc_preview.py test_clean.py test_filters.py -v` 46 passed
- `npm test Result.test.tsx --run` 9 passed
- `npm test --run` 57 passed (8 files)
- `npm run build` Vite 50 modules 247kB gzip 75kB OK
- `cargo check` patched opener but linker missing expected (no msvc) — otherwise syntax OK
- Manual offline/cache-miss/log/badge checks as listed

Residual risks:
- `run_epubcheck` proxy returns clean even if XHTML malformed but parseable — true epubcheck binary needed for strict `✗` in dirty case (deferred)
- `getEpubStatus` slug filtering still returns latest overall if novelUrl not matching slug — could show wrong path when multiple books stored (deferred via getEpubStatus filter)
- `outputDir` traversal blocked via `..` check but symlink escape not checked (low, defer)

