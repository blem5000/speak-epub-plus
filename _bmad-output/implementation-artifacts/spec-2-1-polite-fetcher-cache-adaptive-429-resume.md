---
title: 'Polite Fetcher + cache + adaptive 429 + resume'
type: 'feature'
created: '2026-08-28'
status: 'done'
baseline_commit: 'b4f58ac4abc4c0ac2bb51075b04cfac458e1c328'
review_loop_iteration: 1
context:
  - _bmad-output/specs/spec-speak-epub/SPEC.md
  - _bmad-output/planning-artifacts/architecture/architecture-speak-epub-2026-08-27/ARCHITECTURE-SPINE.md
  - _bmad-output/implementation-artifacts/epic-2-context.md
  - _bmad-output/planning-artifacts/epics.md
---

<frozen-after-approval reason="human-owned intent â€” do not modify unless human renegotiates">

## Intent

**Problem:** Po wyborze zakresu `1â€“100` w Chapter List brak grzecznego pobierania â€” brak sekwencyjnego `3â€“5s+jitter/10s safe`, brak `sha1(url)` cache `_cache/<hash>/raw.html`, brak `adaptive 429` i `resume`, wiÄ™c 100-chapter fetch banuje i re-run pobiera wszystko ponownie.
**Approach:** ZbudowaÄ‡ `core/fetch.py` polite fetcher (sequential, jitter, safe tier, `throttleChanged` event) z Core-owned `cacheKey=sha1(normalized_url)` + dyskowy `_cache` + `resume` diff (bounded `missing-only` vs open-ended `re-validate listChapters`), wire `handle_rpc fetchChapter(s)` â†’ GUI badge/log + resume, bez parallel scrape.

## Boundaries & Constraints

**Always:** `GUIâ†’Coreâ†’Portâ†’Adapter` (`coreâ†’adapters` tylko dynamic `importlib` jak `config.py:152` documented `.importlinter`); politeness owned by `core/fetch.py` `AD-3` `3â€“5s jitter default` / `10s safe` + `adaptive 429 jitter exponential cap 20s` â†’ `throttleChanged` `AD-6`; cache owned by Core `sha1(normalized_url)` `AD-9` `_cache/<hash>/raw.html` `raw` never filtered `AD-2` utf-8, `Core` mutates state `AD-5`; `NFR1` sequential only even though TTS `parallel 2â€“3` later; chapter `1..N` spine order `ports.py:37`; event bus `chapterStatus/logLine/throttleChanged/done` `AD-6` no polling; `core/config.py:get_venv_python` `Scripts/python.exe` Win `AD-4`.
**Ask First:** Zmiana `ScraperPort`/`ChapterInfo`/`store.json` selection persistence vs `_cache` shape (`URL` vs `URL+hash` vs `ETag` `ARCHITECTURE-SPINE.md:191`) + eviction; dodanie dep poza `requests/bs4/lxml` + `requests` juÅ¼; zmiana `ScraperPort.fetchChapter` kontraktu; wirtualizacja/drag poza scope.
**Never:** `clean` selektory/preview `2.2`, filtry `2.3`, EPUB `2.4`, TTS/M4B `Epic3`, `react-window` dla kolejki, parallel scrape, hardcode strings/strings poza `t()`, manual dark toggle, `fetchChapter` mock â€” woÅ‚aÄ‡ real `adapters/novelphoenix.py:200 fetchChapter` via `Port`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Sequential polite | `selected 1â€“100` `NovelPhoenix` `142` via `listChapters` | `fetch 1..100 sequential` `delay 3â€“5s+jitter` default, `raw.html` each to `_cache/<sha1>/raw.html` owned by Core, `no parallel` even if GUI clicks Start twice (queue locked) | `429/5xx/timeout` â†’ retry `min(20,2*attempt)` jitter, `throttleChanged safe` badge |
| Adaptive 429 | `GET https://.../chapter/42` returns `429` `Retry-After: 5` | increment tier `politeâ†’safe 10s`, `jitter 0.2â€“0.6s`, emit `throttleChanged {tier:safe,delay:10000}`, log `retry 1/5 429 chapter 42`, continue `43` after backoff | after 5 retries `LIST_FAILED` per chapter, skip to next chapter, `logLine error` `chapterStatus error` |
| Bounded resume | `_cache` has `1â€“20` `raw` `selected 20â€“100` re-run | `diff desired 20..100 vs cache` â†’ `badge pominiÄ™to 20, pobieram 21â€“100` + `log skipped 20`, fetch only `21..100` missing, `21â€“100 raw` appended to cache | `cacheKey` `sha1(normalized_url)` `core/fetch.py:65` `_normalize_cache_key` reused, `None` non-iterable â†’ `LIST_FAILED` per `config.py:306` |
| Open-ended re-validate | `selected to-end` (no `to`) cache `1â€“100` but site now `142` | `re-validate listChapters` fresh `142` titles `ordered 1..N` `dedupe` â†’ diff `101..142` new, fetch only `101..142`, badge `pominiÄ™to 100, wykryto 42 nowe` | `listChapters 404/timeout` â†’ `LIST_FAILED` `chapterStatus error` + toast `errorList` |
| Cache normalize | `https://www.novelphoenix.com/novel/123` vs `https://www.novelphoenix.com:443/novel/123` vs `https://www.novelphoenix.com./novel/123` | `sha1(_normalize_cache_key)` `config.py:65` host lower+port distinct, trailing dot stripped, `query/fragment` stripped, same novel hits same `_cache` | `ftp://` `""` `no-host` â†’ `VALUE_ERROR` without network `config.py:269` |
| Throttle badge | `Core emit throttleChanged` polite `4000` vs safe `10000` | GUI `Queue` header badge `polite/safe` `log pane role=log aria-live` auto-scroll, no polling | `store write` `save_store` `tmp.replace` atomic, concurrent lose ok (single desktop) |

</frozen-after-approval>

## Code Map

- `Speak-EPUB-1.0.0/core/fetch.py` â€” **NEW** â€” polite fetcher: `delay 3â€“5s+jitter` `AD-3` `random.uniform(3,5)+jitter 0.2â€“0.6` safe `10s`, `fetch_one(url, adapter, cache_dir)` `sha1(normalized_url) â†’ _cache/<hash>/raw.html` `AD-9` owns key, `fetch_many(urls, adapter, desired_range, cache, on_status, on_log, on_throttle)` sequential loop, `adaptive 429` `Retry-After?` `min(20,2*attempt)` + `throttleChanged` emit, `resume` `bounded diff vs cache` vs `open-ended re-validate listChapters` via `adapter.listChapters(novel_url)`, raw never filtered `AD-2` `text` vs `html`
- `Speak-EPUB-1.0.0/core/config.py:257-371,374-496` â€” **EXTEND** â€” add `elif method==\"fetchChapter\"` + `fetchChapters` batch mirroring `listChapters` `257` dynamic `importlib NovelPhoenixAdapter` + `getSelection` reuse `373`, `_normalize_cache_key 65` reuse `query stripped`, `handle_rpc` maps `VALUE_ERROR/LIST_FAILED` vs `[]`, serialize `index/title/url/cover_url`, keep `search/listChapters` `166-302` untouched; document `.importlinter` exception `config.py:152` `coreâ†’adapters` dynamic
- `Speak-EPUB-1.0.0/core/ports.py:13-81` â€” **READ-ONLY** â€” `ScraperPort.search/listChapters/fetchChapter/getSelectors` frozen `ChapterInfo(index,title,url)` `SearchResult(cover_url)` `AdapterError code LIST_FAILED` â€” AD-1 firewall, verify `issubclass`
- `Speak-EPUB-1.0.0/adapters/novelphoenix.py:200-268` â€” **REUSE** â€” `fetchChapter(url)` production `_get 127` `12s retries2` `min(20,2*attempt)` jitter, isolate via `getSelectors start=\"div#chapter-content\"` else `heuristic article/div.chapter-content`, strip `script/style/nav/aside` â€” `AD-7` source of truth, provide `_last_cover_url` not needed here
- `Speak-EPUB-1.0.0/adapters/_http.py:24` â€” **READ-ONLY** â€” `_get(url,timeout=12,retries=2)` UA `SpeakEPUB/1.0` jitter `0.2-0.6` retry `min(20,2*attempt)` 5xx/timeout 2x â€” adapter-local to avoid `adaptersâ†’core.fetch` `AD-1`
- `Speak-EPUB-1.0.0/adapters/base.py:33` â€” **READ-ONLY** â€” `guess_adapter` host-suffix `==/endswith` not `in` â€” prevents spoof `evilnovelphoenix.com`
- `src/hooks/useChapterList.ts:18-189` â€” **READ-ONLY** â€” `listChapters` 5s `AbortController` + `callIdRef` + early `host guard` `50` `VALUE_ERROR/LIST_FAILED` mapping, `cover` plumbing `useChapterList.ts:121` â€” reuse pattern for `useFetcher` if needed
- `src/lib/sidecar.ts:25-121` â€” **REUSE** â€” `callSidecar python_sidecar_call` fallback `http://localhost:17381` id check `55`, `ABORTED` mapping `85`, `onThrottleChanged` `158` `ThrottleChangedEvent` already typed `AD-6`
- `src/App.tsx:29-180,358-460` â€” **EXTEND** â€” wire `fetch` button `Start` disabled when `chapterLoading` or `N===0`, `hasSelectedUrl` guard `184`, `showChapterSkeleton` `186`, `showChapterList` `186`, plus new `Queue` minimal section `fetchâ†’cleanâ†’build` later: per-chapter `chapterStatus queued/fetching/cleaning/done/error` + `logLine role=log aria-live` + `throttle badge polite/safe` + `resume badge pominiÄ™to N` â€” keep `Find` `useDebouncedSearch` `17` + `selectedUrl` reset `94-106` + `skipNextClearRef` `26`
- `src/components/ChapterList.tsx:1-274` â€” **READ-ONLY** â€” range `odâ€“do` `clampRange` `RangeBar.tsx:65` + `selected Set` sync `App.tsx:29` Core-owned `getSelection/setSelection` `config.py:373` â€” reuse, not modify for 2.1
- `Speak-EPUB-1.0.0/tests/test_novelphoenix.py:200-324` â€” **REF** â€” `fetchChapter` isolations `test_fetchChapter_via_selector 71%` etc. â€” oracle for `core/fetch` integration
- `Speak-EPUB-1.0.0/tests/test_handle_rpc_listchapters.py:1-158` â€” **REF** â€” `VALUE_ERROR/LIST_FAILED` `port/userinfo stripped` `cache poisoning deep copy` patterns â€” reuse for `fetchChapter` RPC tests
- `_cache/` â€” **NEW DIR** â€” `gitignore` already `*_audiobook/` but not `_cache/` â€” add `Speak-EPUB-1.0.0/_cache/` + `.gitkeep` per `AD-9` raw `utf-8` `raw.html`
- `.importlinter:12` â€” **READ-ONLY** â€” `core-no-adapters` / `adapters-no-pipeline` contracts â€” keep `core.config dynamic import` exception `config.py:152`

## Tasks & Acceptance

**Execution:**
- [x] `Speak-EPUB-1.0.0/core/fetch.py` â€” NEW `cache_key(url)=sha1(_normalize_cache_key(url))` owned by Core `AD-9`, `get_cache_path(url) â†’ Path(\"_cache/<hash>/raw.html\")`, `read_cache / write_cache` utf-8, `polite_delay(tier)` `3â€“5s+ jitter 0.2â€“0.6` default `10s` safe, `fetch_one` sequential `requests` via `adapters._http._get` or direct `requests.get` 12s `2 retries` `min(20,2*attempt)`, maps `429/5xx/timeoutâ†’LIST_FAILED` after 5 retries, emits `on_throttle(tier,delay)` + `on_log(line)` + `on_status(idx,status)`, `fetch_many` bounded `diff vs cache` vs open-ended `adapter.listChapters(novel_url)â†’re-validate` â€” rationale `NFR1` politeness + `NFR3` resume + `AD-3/9`
- [x] `Speak-EPUB-1.0.0/core/config.py` â€” EXTEND `elif method in (\"fetchChapter\",\"fetchChapters\",\"getCacheStatus\"):` validate `^https?://` `host` `VALUE_ERROR` `host guard` `LIST_FAILED unsupported host` `-importlib NovelPhoenixAdapter` + `core/fetch.py fetch_one/fetch_many` reuse `cache_key`, serialize `ChapterContent(url,title,html,text)` + `cover?`, map `AdapterError LIST_FAILED` â†’ `{\"error\":{\"code\":\"LIST_FAILED\"}}`, keep `search/listChapters` `166-302` + `getSelection` `373-496` untouched â€” rationale `FR3` real fetch via Port `AD-1`
- [x] `src/lib/sidecar.ts` â€” EXTEND type guards for `fetchChapter(s)` `callSidecar(\"fetchChapters\",{urls:[], novelUrl, from, to})` + existing `onThrottleChanged` `158` `onLogLine` `153` `onChapterStatus` `143` already `AD-6` â€” no new transport `sidecar.ts:25` â€” rationale `AD-4/6` bus no polling
- [x] `src/App.tsx` + `src/hooks/useFetcher.ts` (NEW hook optional) â€” wire `Start` `fetchChapters` `selected` `chapterList` `from/to` `N` â†’ `callSidecar fetchChapters` `AbortController 5s` per chapter? reuse `useChapterList.ts:70` `callIdRef` pattern, states `fetching/list/log/throttle`, render minimal `Queue` `App.tsx:358` `section` when `fetching` + `hasSelectedUrl && !chapterLoading`, badge `pominiÄ™to N` `log pane role=log aria-live` + `throttle badge polite/safe` `logLine` â€” keep `Find` + `ChapterList` `App.tsx:13-22` wire â€” rationale `FR3` polite + `FR6` live per-chapter `UX-DR5` minimal
- [x] `Speak-EPUB-1.0.0/tests/test_fetch.py` â€” NEW `pytest` `fetch_one` `sha1` + `cache hit` + `429 adaptive safe` `min(20,backoff)` + `bounded diff 20â€“100` `open-ended re-validate 142` + `VALUE_ERROR` `unsupported host` + `None non-list` `LIST_FAILED` â€” mocked `requests.get` `adapters/novelphoenix` `fetchChapter` + `listChapters` â€” rationale `NFR1/NFR3` verification before GUI
- [x] `Speak-EPUB-1.0.0/tests/test_handle_rpc_fetch.py` â€” NEW `VALUE_ERROR empty/ftp/no-host`, `LIST_FAILED unsupported`, `IMPORT_FAILED`, `fetchChapter 1 chap html/text` + `fetchChapters batch 20â€“100 skip cached`, `cover fallback` â€” pattern `test_handle_rpc_listchapters.py:13` `handle_rpc` mock `MockAdapter fetchChapter` â€” rationale `FR3` RPC contract pin
- [x] `src/hooks/useFetcher.test.tsx` â€” NEW `renderHook` `useFetcher(urls)` `3â€“5s delay` mocked `callSidecar` `throttleChanged` `LIST_FAILED` mapping, bounded `skip` `21â€“100`, open-ended `101â€“142` new detection â€” pattern `useChapterList.test.tsx:22` `vi.mock sidecar` â€” rationale `UX-DR5` throttle badge
- [x] `.gitignore` + `Speak-EPUB-1.0.0/_cache/.gitkeep` â€” ensure `_cache/` ignored? Actually raw `ut-8` must persist for resume â€” keep `!_cache/` or add `.gitkeep` but ignore `*.mp3` already â€” do not ignore `_cache/*.html` per `AD-9` resume â€” rationale `NFR3`

**Acceptance Criteria:**
- Given `selected 1â€“100` gdy `Start` fetch via `core/fetch.py` `fetch_many`, then `100` `raw.html` sequential `3â€“5s+jitter` `no parallel` `sha1(normalized_url)` `_cache/<hash>/raw.html` owned by Core `AD-9`, `throttleChanged safe` po `429` `jitter exponential cap 20s` badge `safe` w GUI, `logLine retry 1/5`.
- Given `_cache 1â€“20` istnieje gdy `20â€“100` re-run bounded, then tylko `21â€“100` fetch `badge pominiÄ™to 20, pobieram 21â€“100` + `log skipped _cache/*.html`; gdy `to-end` open-ended `1â€“100` cached a site `142`, then `re-validate listChapters 142` â†’ `101â€“142` fetch only.
- Given `handle_rpc fetchChapter(s)` gdy `callSidecar(\"fetchChapters\",{urls})` via `sidecar.ts:25`, then `VALUE_ERROR` dla `\"\"/ftp/no-host` bez sieci, `LIST_FAILED unsupported host` dla `evil.com`, `IMPORT_FAILED` gdy `adapters.novelphoenix` missing, `200.html` `ChapterContent` `html/text` dla `1 chap`.
- Given `fetch` sequential gdy `N=100` bez banu (<5s per site parallel juÅ¼, fetch sequential `3â€“5s`), then `100-chapter polite scrape bez ban` `NFR1` oraz `5 retries backoff min(20,2*attempt)` pin w `test_fetch.py`.
- Given `Queue` minimal gdy `fetchâ†’clean` leci, then `per-chapter pill queued/fetching/cleaning/done/error` + `log pane role=log aria-live` + `resume badge` w `App.tsx` `Queue section` (peÅ‚ny TTS nie).

## Spec Change Log


## Verification

**Commands:**
- `Speak-EPUB-1.0.0/venv/Scripts/python.exe -m py_compile Speak-EPUB-1.0.0/core/fetch.py Speak-EPUB-1.0.0/core/config.py` -- 0 exit, `fetch_one` importable
- `Speak-EPUB-1.0.0/venv/Scripts/python.exe -m pytest Speak-EPUB-1.0.0/tests/test_fetch.py -v` -- polite delay mocked, cache hit, 429 safe, bounded diff, open-ended re-validate â€” pass
- `Speak-EPUB-1.0.0/venv/Scripts/python.exe -m pytest Speak-EPUB-1.0.0/tests/test_handle_rpc_fetch.py -v` -- VALUE_ERROR/LIST_FAILED/IMPORT_FAILED + fetchChapter batch â€” pass
- `Speak-EPUB-1.0.0/venv/Scripts/python.exe -m pytest Speak-EPUB-1.0.0/tests/test_handle_rpc_listchapters.py -v` -- still 13/13, `_CHAPTER_CACHE` not broken
- `npm test -- src/hooks/useFetcher.test.tsx -v` -- throttle badge, bounded skip, open-ended new â€” pass
- `npm run build` -- Vite build success, `useFetcher` included, `var(--ring)` present
- `cargo check --manifest-path src-tauri/Cargo.toml` -- Tauri 2.11.5 resolve OK (or linker missing warning not code)
- `Speak-EPUB-1.0.0/venv/Scripts/python.exe -c "from core.fetch import cache_key; print(cache_key('https://www.novelphoenix.com/novel/123'))"` -- 40 hex `sha1`

**Manual checks (if no CLI):**
- `Find` â†’ `novelphoenix` â†’ `ChapterList` `1â€“20 Zaznacz` â†’ `Start` â†’ `Queue` shows `fetching 1..20` sequential `3â€“5s`, `_cache/<hash>/raw.html` 20 files, badge `polite`; trigger `429` (mock `http 429`) â†’ badge `safe 10s` + `log retry` + continue; re-run `20â€“100` â†’ badge `pominiÄ™to 20` + `21â€“100` only; open-ended `to-end` with site now `142` â†’ badge `wykryto 42 nowe` + `101â€“142` fetched.

## Suggested Review Order

**Fetch â€” cache & politeness (entry point)**

- `cache_key = sha1(_normalize_cache_key)` owns `_cache/<hash>/raw.html` `AD-9` â€” never filtered `AD-2`
  [`fetch.py:18`](../../Speak-EPUB-1.0.0/core/fetch.py#L18)

- Polite delay `3â€“5s jitter / 10s safe` `AD-3` + `min(20,2*attempt)` exponential â€” `throttleChanged` emit
  [`fetch.py:34`](../../Speak-EPUB-1.0.0/core/fetch.py#L34)

- Sequential loop `fetch_many` no parallel scrape even if GUI double clicks `Start`
  [`fetch.py:52`](../../Speak-EPUB-1.0.0/core/fetch.py#L52)

**Config â€” RPC mapping**

- `handle_rpc fetchChapter(s)` `VALUE_ERROR` `LIST_FAILED` `IMPORT_FAILED` vs `[]` â€” decides toast vs `[]`
  [`config.py:257`](../../Speak-EPUB-1.0.0/core/config.py#L257)

- Dynamic `importlib NovelPhoenixAdapter` keeps `GUIâ†’Coreâ†’Portâ†’Adapter` `AD-1` `.importlinter:12`
  [`config.py:291`](../../Speak-EPUB-1.0.0/core/config.py#L291)

- `getSelection/setSelection` untouched `373` â€” selection persistence not moved to fetch

**Adapter â€” reuse**

- `fetchChapter` via `getSelectors else heuristic` `novelphoenix.py:200` `AD-7` â€” strip `script/style`

- `_get` UA `SpeakEPUB/1.0` `12s retries2` `_http.py:24` â€” not `core/fetch`

**GUI â€” Queue minimal**

- `App.tsx Queue section` `chapterStatus/logLine/throttleChanged` `role=log aria-live` `throttle badge`
  [`App.tsx:358`](../../src/App.tsx#L358)

- `useFetcher` `AbortController` + `callIdRef` + `5s` race like `useChapterList.ts:70` â€” no `ABORTED` flash

- `sidecar.ts onThrottleChanged 158` already typed `AD-6` â€” no new transport

**Tests & contracts**

- `test_fetch.py` polite/cache/429/bounded/open-ended â€” pin `NFR1/3`

- `test_handle_rpc_fetch.py` `VALUE_ERROR/LIST_FAILED` â€” contract for `sidecar.ts:25`

- `useFetcher.test.tsx` throttle + resume badges â€” GUI minimal

### Review Findings

> Code review 2026-08-28 â€” 3 decision, 14 patch, 3 defer, 12 dismissed â€” diff `b4f58ac...888f43f` (10 files, 2059 insercji). Tryb `full` vs spec + EPIC-2 context.

#### Decision Needed â€” wymaga Twojej decyzji (human-owned intent)

- [x] [Review][Decision] Bounded resume badge â€” czy `pominiÄ™to N` liczy overlap czy wybrany zakres? â€” Spec `Bounded resume` oczekuje `badge pominiÄ™to 20, pobieram 21â€“100` gdy `_cache 1â€“20` + `selected 20â€“100`, ale `core/fetch.py:504-537` liczy `skipped=sum(read_cache)`=1 (tylko `20` wspÃ³lny) â†’ badge `pominiÄ™to 1, pobieram 2â€“81`. `tests/test_fetch.py:1225` komentuje rozbieÅ¼noÅ›Ä‡. Decyzja: czy badge ma opieraÄ‡ siÄ™ na przeciÄ™ciu URL-i (`desired âˆ© cache`) czy na liczbie rozdziaÅ‚Ã³w w cache dla zakresu `fromâ€“to` niezaleÅ¼nie czy `20â€“100` zawiera `1â€“19`? Wymaga wyboru semantyki i poprawki badge `pobieram Xâ€“Y` (obecnie `skipped+1â€“skipped+len(missing)` nie `from+offset`). AC2.
- [x] [Review][Decision] Nowy kod `LOCKED` spoza I/O Matrix â€” czy dozwolony? â€” `core/fetch.py:403` zwraca `{"error":"LOCKED","badge":"queue locked"}` przy `acquire(blocking=False)` + `core/config.py:665` mapuje na `{"code":"LOCKED"}`, ale I/O Matrix definiuje tylko `VALUE_ERROR/LIST_FAILED/IMPORT_FAILED` (plus `EXCEPTION`). GUI `src/App.tsx:540` nie obsÅ‚uguje `LOCKED` toast vs `LIST_FAILED`. Decyzja: zachowaÄ‡ `LOCKED` jako nowy kontrakt dla `queue locked` (GUI pokazuje "kolejka zajÄ™ta, sprÃ³buj ponownie") czy zmapowaÄ‡ na `LIST_FAILED`/`EXCEPTION` z komunikatem?
- [x] [Review][Decision] Live event bus `AD-6` vs batch return â€” czy 2.1 wymaga strumieniowego `throttleChanged/logLine/chapterStatus`? â€” `core/fetch.py:644-601` zbiera `throttles/logs/statuses` i zwraca w `result` po koÅ„cu, nie `emit` Tauri `chapterStatus/logLine/throttleChanged`. `src/hooks/useFetcher.ts:38-72` subskrybuje `onThrottleChanged/onLogLine/onChapterStatus` live ale nigdy nie fire'uje; badge/log aktualizujÄ… siÄ™ dopiero po `fetchChapters` (5 min dla 100 rozdziaÅ‚Ã³w brak postÄ™pu). Spec Boundaries `Always: event bus chapterStatus/logLine/throttleChanged/done AD-6 no polling` wymaga live. Decyzja: dopisaÄ‡ `emit` w `core` (wymaga Rust `emit`) dla live Queue czy zaakceptowaÄ‡ batch badge dla minimal Queue 2.1 i odÅ‚oÅ¼yÄ‡ live do Epic 4?

#### Patch â€” do poprawki bez decyzji (code fix)

- [x] [Review][Patch] `write_cache` nieatomowy + brak obsÅ‚ugi corrupt/empty `raw.html` [`Speak-EPUB-1.0.0/core/fetch.py:74-79`] â€” `p.write_text` bez `tmp.replace`, kill w poÅ‚owie zostawia truncated `raw.html`; `read_cache:63-71` zwraca truncated jako hit i `fetch_one:146-177` syntezuje `ChapterContent` z uszkodzonego HTML. Fix: `tmp=p.with_suffix('.tmp'); tmp.write_text(..., 'utf-8'); tmp.replace(p)` + w `read_cache`/`fetch_one` sprawdÅº `cached.strip()` i brak `html` â†’ treat as miss + test corrupt/empty.
- [x] [Review][Patch] `fetch_one` zawsze `on_status(0, ...)` + `fetch_many` `ch_num` miscalc [`Speak-EPUB-1.0.0/core/fetch.py:154-155,554`] â€” cache-hit i single fetch raportujÄ… `chapter 0` zamiast `ch.index`; `fetch_many` liczy `ch_num=(from_idx+idx)+skipped` co dla `selected 50â€“60` mapuje na `1..11`. Fix: `fetch_one` przyjmij `chapter_index` param, `fetch_many` mapuj `desired_urls -> ch.index` via `chapterIndexMap` i uÅ¼ywaj go dla `on_status`; `useFetcher` inicjalizuj `statuses` po `ch.index` nie `idx+1`.
- [x] [Review][Patch] `urls` jako `tuple` omija walidacjÄ™ hosta [`Speak-EPUB-1.0.0/core/config.py:523`] â€” `if isinstance(urls, list)` nie Å‚apie `tuple`; walidacja pominiÄ™ta â†’ `evil.com` przejdzie. Fix: `if isinstance(urls, (list, tuple))` + dodaj guard `len(urls)>1000` i dedup przed `fetch_many`.
- [x] [Review][Patch] `404/403` traktowane jako retryable â€” 5Ã— bezsensowny backoff [`Speak-EPUB-1.0.0/core/fetch.py:235`] â€” `retryable = ... or code in ("FETCH_FAILED","LIST_FAILED")` retry'uje permanentne `404`. Fix: `retryable = is_429 or is_5xx or is_timeout` tylko; dla `code in ("LIST_FAILED") and "404" in msg` â†’ `retryable=False` + natychmiast `LIST_FAILED`.
- [x] [Review][Patch] `max_retries` 0/negative koÅ„czy `RuntimeError` [`Speak-EPUB-1.0.0/core/fetch.py:188`] â€” `for attempt in range(1, max_retries+1)` puste â†’ `raise RuntimeError`. Fix: `if max_retries < 1: raise ValueError`.
- [x] [Review][Patch] Silent drop non-string `urls` + brak limitu payload [`Speak-EPUB-1.0.0/core/fetch.py:386`] â€” `[u for u in urls if isinstance(u,str)]` cicho usuwa `None/int`. Fix: waliduj i `raise VALUE_ERROR` jeÅ›li `any(not isinstance(u,str) ...)`, dodaj `if len(urls)>500: raise VALUE_ERROR "too many urls"`.
- [x] [Review][Patch] Brak dedup duplicate URLs â€” zawyÅ¼a `skipped` [`Speak-EPUB-1.0.0/core/fetch.py:809`] â€” `desired` z `adapter.listChapters` lub `urls` moÅ¼e zawieraÄ‡ duplikaty. Fix: `desired=list(dict.fromkeys(desired))` po `sorted`.
- [x] [Review][Patch] `to_idx=0` klasyfikowany jako bounded [`Speak-EPUB-1.0.0/core/fetch.py:390`] â€” `is_open_ended = (to_idx is None) and novel_url` nie Å‚apie `0`. Fix: `is_open_ended = (to_idx is None or to_idx <1) and novel_url is not None`.
- [x] [Review][Patch] `sidecar.ts` type-guardy sÅ‚abe + brak `trim`/limit [`src/lib/sidecar.ts:225-230`] â€” `isFetchChapterResult` tylko `html in result`, brak walidacji `throttles` shape. Fix: zaostrzyÄ‡ guard + `params.urls` `trim()` i `if urls.length>500 throw`.
- [x] [Review][Patch] `useFetcher` statuses `idx+1` vs `ch.index` + failed nadal `done` [`src/hooks/useFetcher.ts:104-110,187-197`] â€” inicjalizacja `initial[idx+1]="queued"` nie dla `selected 50â€“60`; po fetch `fetchedCount+skipped` oznacza `done` teÅ¼ dla `failed`. Fix: inicjalizuj po `ch.index`, po `result` oznacz `failed` jako `error` nie `done`, uÅ¼yj `chapterIndexMap`.
- [x] [Review][Patch] `App.tsx` Queue slice `0,20` + `cleaning` identyczny z `queued` + a11y [`src/App.tsx:546-587`] â€” `slice(0,20)` ukrywa `21â€“100`; `st==="cleaning"` wpada w `bg-muted` jak `queued` bez ikony/text-alt; `role=log` bez `aria-label`/`tabIndex`. Fix: virtualizuj lub pokaÅ¼ `+N more`, distinct `cleaning` pill `bg-info`, dodaj `aria-label` i `tabIndex=0` + auto-scroll announcement.
- [x] [Review][Patch] Weryfikacja: polite delay miÄ™dzy rozdziaÅ‚ami nigdy nie testowany â€” `skip_delay=True` zawsze [`Speak-EPUB-1.0.0/tests/test_fetch.py:195`] â€” brak asercji `time.sleep` `N-1` razy `3.2â€“5.6`/`10.0`. Fix: dodaÄ‡ test `fetch_many` `skip_delay=False` mock `time.sleep` + `random.uniform` â†’ `call_count==2`.
- [x] [Review][Patch] Weryfikacja: `5xx/timeout` i `Retry-After` header nie pokryte [`Speak-EPUB-1.0.0/core/fetch.py:229-324`] â€” tylko `429` testowane, `is_5xx`/`is_timeout` bez testu; `Retry-After` tylko numeric, brak testu Å¼e `max(wait,int(ra))` honorowany. Fix: dodaÄ‡ testy `500` + `timeout` retry oraz `AdapterError` z `response.headers={"Retry-After":"10"}`.
- [x] [Review][Patch] Weryfikacja: per-chapter partial-failure `continue` nie pokryte [`Speak-EPUB-1.0.0/core/fetch.py:577-602`] â€” wszystkie `TestFetchMany` mockujÄ… sukcesy; `break` zamiast `continue` nie psuje testÃ³w. Fix: dodaÄ‡ test `side_effect` raise dla `urls[1]` tylko â†’ assert `len(results)==2`, `len(failed)==1`, next fetch nadal.
- [x] [Review][Patch] Weryfikacja: `getCacheStatus` `novelUrl+from/to` slicing nie pokryty [`Speak-EPUB-1.0.0/core/config.py:542-606`] â€” tylko `urls` branch testowany `test_getCacheStatus`. Fix: dodaÄ‡ test `novelUrl + from=20 to=100` + invert `100â†’20` + out-of-bounds wobec 142 mock + `re-validate`.
- [x] [Review][Patch] `.gitignore` negacja nie rekurencyjna [` .gitignore:62`] â€” `!Speak-EPUB-1.0.0/_cache/` + `!.../.gitkeep` nie odsÅ‚ania `*/<hash>/raw.html` jeÅ›li dodano `*.html` ignore. Fix: dodaÄ‡ `!Speak-EPUB-1.0.0/_cache/**` (+ `!Speak-EPUB-1.0.0/_cache/*/raw.html`) i komentarz `raw.html must persist`.
- [x] [Review][Patch] Retry log uÅ¼ywa peÅ‚nego URL zamiast `chapter 42` [`Speak-EPUB-1.0.0/core/fetch.py:259`] â€” `on_log(f"retry {attempt}/{max_retries} 429 chapter {url}")` loguje caÅ‚y URL, I/O Matrix oczekuje `chapter 42`. Fix: wyciÄ…gnij numer z URL lub `ch_num` i loguj `chapter {idx}`.
- [x] [Review][Patch] `logs` unbounded + initial throttle `4000` poza `3.2â€“5.6` [`src/hooks/useFetcher.ts:29,52`] â€” `logs` rosnÄ… bez limitu dla 100Ã—5 retry; `useState({tier:"polite",delay:4000})` nie w `3200â€“5600`. Fix: `throttle` inicjalizuj `null` lub `polite_delay` z Core, `logs` cap `200` `slice(-200)`.

#### Defer â€” odroczone, pre-existing / Ask First

- [x] [Review][Defer] `_normalize_cache_key` brak NFC/IDNA/percent-encoding â€” duplicate cache dla `novel%2F123` [`Speak-EPUB-1.0.0/core/fetch.py:31`] â€” deferred, pre-existing â€” poza spec `host lower+port distinct+trailing dot+query/fragment stripped`, NFC/punycode/percent nie wymagane w 2.1.
- [x] [Review][Defer] Dynamic `importlib` per RPC bez cache â€” duplikacja 4Ã— `_il` [`Speak-EPUB-1.0.0/core/config.py:399`] â€” deferred, pre-existing â€” optymalizacja, nie funkcjonalny, `IMPORT_FAILED` path testowany.
- [x] [Review][Defer] i18n Polish w Core (`pominiÄ™to`/`wykryto`) vs `t()` â€” [`Speak-EPUB-1.0.0/core/fetch.py:448`] â€” deferred, pre-existing â€” spec `Tasks` definiuje badge Polish w Core, `Never hardcode poza t()` Ask First dla TTS, akcept w 2.1.

> Odrzucono jako szum: 12 â€” concurrency `threading.Lock` + `_FETCHING` (spec `NFR1 sequential` intencjonalnie, `LOCKED` ok dla single desktop), cache-hit fabric via `BeautifulSoup` (raw `AD-2`, heuristic AD-7 dopiero 2.2), host lower/port distinct juÅ¼ per spec, `from/to` clamp mismatch (backend i tak clamp), event `AbortController` leak teoretyczny (brak cancel UI w 2.1), itp. â€” patrz triage.


