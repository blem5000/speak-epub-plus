---
title: 'Adapter NovelPhoenix — search + listChapters + cover/metadata'
type: 'feature'
created: '2026-08-27'
status: 'done'
baseline_commit: '8918b6a453dec289dde346172948deeee79f5403'
review_loop_iteration: 0
context:
  - _bmad-output/specs/spec-speak-epub/SPEC.md
  - _bmad-output/planning-artifacts/architecture/architecture-speak-epub-2026-08-27/ARCHITECTURE-SPINE.md
  - _bmad-output/implementation-artifacts/epic-1-context.md
  - _bmad-output/planning-artifacts/epics.md
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `adapters/novelphoenix.py:15` is mock (`NotImplementedError`) so discovery has no data — Find cannot show `site|title|chapters|link` and Chapter List cannot load 1..N with cover.

**Approach:** Implement `NovelPhoenixAdapter` over `ScraperPort` (polite `requests`+`BeautifulSoup`) plus `core/aggregator.py` parallel fan-out, keeping `GUI→Core→Port→Adapter` and spine-order 1..N.

## Boundaries & Constraints

**Always:** `GUI→Core→Port→Adapter`; adapters never import `core.fetch/clean/epub/tts/merge/aggregator/config` (`.importlinter:15` AD-1, `core/ports.py:49`); venv via `core/config.py:get_venv_python()` Win `Scripts/python.exe` vs POSIX `bin/python`; chapter id 1..N spine order; selectors owned by adapter via `getSelectors()` (`adapters/novelphoenix.py:24`), heuristic only fallback; sequential fetch only; `SearchResult`/`ChapterInfo`/`ChapterContent` frozen; UA `SpeakEPUB/1.0`.

**Ask First:** Extending `ScraperPort` beyond `cover_url` on `SearchResult`; adding deps beyond `requests/bs4/lxml`; changing `sha1(normalized_url)` cache ownership; touching `speak.py:extract_chapters` or `PartJob`.

**Never:** Polite cache/resume tiers + adaptive 429 (Epic 2.1), clean/preview/filters (2.2/2.3), EPUB/epubcheck (2.4), TTS/M4B (Epic 3), Find/ChapterList UI (1.3/1.4), parallel scrape, hard-coded strings.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Search hit | `title="Lord of Mysteries"` reachable | `List[SearchResult]` with `site="novelphoenix.com"`, `url` absolute, `title` non-empty, `chapter_count` via regex `(\d+)` or `None`, <5s single-site; aggregator <5s per site parallel | 4xx/5xx/timeout after 2 retries `min(20,2*attempt)` → `[]` + log "search failed <site>: <code>" no raise |
| Search empty/validate | `title="zzzz_no_match"` or `""`/whitespace/len>300 | `[]` for no match; `ValueError` for empty/whitespace; truncate >300 to 200 before request | No network on validation error |
| listChapters hit | Novel URL HTML with `og:image` + `142` anchors + 3 noise (`Next`, empty, dupe) | `List[ChapterInfo]` 1..N contiguous ordered, `url` absolute via `urljoin`, dedupe by normalized URL, skip `len<2` or `^(next|prev|cover)$`; cover via `og:image` fallback `img.cover` exposed as `SearchResult.cover_url` else `None` | 0 after filter → `[]`; 404/timeout → `AdapterError LIST_FAILED`; 5xx/timeout retry 2x |
| fetchChapter | Valid chapter URL | `ChapterContent(url,title,html,text)` body via `getSelectors()` else heuristic `article/#content/.chapter-content`, strip `script/style/nav/aside` | 404→LIST_FAILED; 429/5xx retry 2x then error |
| getSelectors | Any | `Selectors(start="div#chapter-content", end=None)` or `None,None` for heuristic; never `""` (`ports.py:19` normalizes) | N/A |

</frozen-after-approval>

## Code Map

- `Speak-EPUB-1.0.0/core/ports.py:13-81` — **PORT** — add `cover_url: Optional[str]=None` (+ `author`) to `SearchResult`; keep `frozen=True`; `adapters/novelphoenix.py:9` imports — AD-1 firewall
- `Speak-EPUB-1.0.0/adapters/novelphoenix.py:12-26` — **IMPLEMENT** — replace mock with `requests`+`BeautifulSoup`: `search` builds `https://www.novelphoenix.com/search?keyword=<quote>` parses `div.book-item`+`a[href]`+`span.chapters`, `listChapters` GETs novel page cover `meta[property="og:image"]`→`img.cover`, chapter anchors `ul.chapter-list li a` or `a[href*=/chapter/]` dedupe/normalize, `fetchChapter` isolates body, `getSelectors` returns `Selectors(start="div#chapter-content")`
- `Speak-EPUB-1.0.0/adapters/_http.py` — **NEW** — adapter-local `_get(url,timeout=12,retries=2)` UA `SpeakEPUB/1.0` jitter 0.2-0.6s retry `min(20,2*attempt)` — avoids `adapters→core.fetch` violation (`.importlinter:19`)
- `Speak-EPUB-1.0.0/adapters/base.py:13-37` — **READ-ONLY** — `guess_adapter` host-suffix `base.py:33-35` prevents query-param spoof; keep `KNOWN_ADAPTERS`
- `Speak-EPUB-1.0.0/core/config.py:17-36` — **READ-ONLY** — `get_venv_python()` OS-aware; `run_sidecar_loop:138` pinned
- `Speak-EPUB-1.0.0/core/aggregator.py` — **NEW** — `search_all(title, adapters)->List[SearchResult]` `ThreadPoolExecutor` 5s per adapter, dedupe `(site,url)`, on `ValueError`/`AdapterError` → `[]`
- `Speak-EPUB-1.0.0/requirements.txt:1-17` + `requirements.txt:1-17` — **MODIFY** — add `requests==2.32.3` keep `beautifulsoup4==4.14.3 lxml==6.0.2`
- `Speak-EPUB-1.0.0/speak.py:91-124` — **REF** — `extract_chapters` spine `<100` skip `speak.py:117` → mirror in `listChapters` filter
- `.importlinter:6-27` + `pyproject.toml:6-27` — **ENFORCE** — contracts `core-no-adapters`, `adapters-no-pipeline`
- `_bmad-output/planning-artifacts/epics.md:107-117` + `epic-1-context.md:1-52` — AC source + parallel <5s
- `spec-1-1-scaffold...md:42-54` — continuity

## Tasks & Acceptance

**Execution:**
- [x] `Speak-EPUB-1.0.0/core/ports.py` — add `cover_url: Optional[str]=None` (and `author`) to `SearchResult` frozen defaults — keep `chapter_count/url` semantics
- [x] `Speak-EPUB-1.0.0/adapters/_http.py` — create `_get` helper UA `SpeakEPUB/1.0` jitter retry `min(20,2*attempt)` 5xx/timeout 2x
- [x] `Speak-EPUB-1.0.0/adapters/novelphoenix.py` — impl `search/listChapters/fetchChapter/getSelectors` as Code Map; normalize URLs `urljoin`, dedupe, filter `len<2`, cover `og:image`, chapter body via selector else heuristic
- [x] `Speak-EPUB-1.0.0/core/aggregator.py` — impl `search_all` parallel 5s timeout, dedupe, fault-isolate per adapter
- [x] `Speak-EPUB-1.0.0/requirements.txt` + `requirements.txt` — pin `requests==2.32.3`
- [x] `Speak-EPUB-1.0.0/tests/test_novelphoenix.py` — mocked `requests.get` fixtures: search 2 results (142 + None), listChapters 142+3 noise ordered/dedupe, cover `og:image` vs fallback, empty → `[]`, selectors non-empty
- [x] `Speak-EPUB-1.0.0/adapters/__init__.py` — export `NovelPhoenixAdapter` factory without pipeline import

**Acceptance Criteria:**
- Given "Lord of Mysteries" mocked search HTML with `site|title|chapters|link`, when `search` called, then returns `site="novelphoenix.com"` `chapter_count` parsed via `(\d+)` absolute `url` <5s; unknown host `evil.com?x=novelphoenix.com` → `guess_adapter` is `None`.
- Given novel URL fixture with `og:image` + 142 anchors + 3 noise/dupe, when `listChapters` called, then returns exactly 142 `ChapterInfo` 1..N contiguous absolute deduped, skips noise, `cover_url` populated else `None` without failure.
- Given `ScraperPort` ABC, when adapter implements, then `issubclass(NovelPhoenixAdapter,ScraperPort)` and `lint-imports` passes (no `core→adapters` nor `adapters→core.pipeline`).
- Given `search_all` with 2 mocks (0.2s,0.8s, one raising), when called, then merges deduped <5s per site, failing adapter contributes `[]`.
- Given empty `""` title when `search` called, then raises `ValueError` without network; len>300 truncates to 200.

## Spec Change Log


## Verification

**Commands:**
- `Speak-EPUB-1.0.0/venv/Scripts/python.exe -m py_compile Speak-EPUB-1.0.0/core/ports.py Speak-EPUB-1.0.0/adapters/novelphoenix.py Speak-EPUB-1.0.0/adapters/_http.py Speak-EPUB-1.0.0/core/aggregator.py` -- 0 exit
- `Speak-EPUB-1.0.0/venv/Scripts/python.exe -c "from core.ports import ScraperPort; from adapters.novelphoenix import NovelPhoenixAdapter; print(issubclass(NovelPhoenixAdapter, ScraperPort))"` -- `True`
- `Speak-EPUB-1.0.0/venv/Scripts/python.exe -m pytest Speak-EPUB-1.0.0/tests/test_novelphoenix.py -v` -- search/listChapters/cover/dedupe/guess all pass
- `Speak-EPUB-1.0.0/venv/Scripts/python.exe -m lint_imports` -- contracts pass
- `Speak-EPUB-1.0.0/venv/Scripts/python.exe -c "from adapters.base import guess_adapter; assert guess_adapter('https://www.novelphoenix.com/book/123')=='novelphoenix'; assert guess_adapter('https://evil.com?x=novelphoenix.com') is None; print('guess ok')"` -- `guess ok`

**Manual checks (if no CLI):**
- Mocked search fixture returns `site|title|chapters|link` with correct `chapter_count`/`cover_url`; empty returns `[]`.
- `listChapters` 142+3 noise fixture deduped 142 ordered contiguous.

## Suggested Review Order

**Port & Contract — entry point**

- Frozen DTO extension keeps AD-1 firewall, verify backward compat
  [`ports.py:27`](../../Speak-EPUB-1.0.0/core/ports.py#L27)

- ScraperPort ABC defines search/listChapters/fetchChapter/getSelectors contract
  [`ports.py:59`](../../Speak-EPUB-1.0.0/core/ports.py#L59)

- AdapterError code taxonomy for LIST_FAILED/FETCH_FAILED
  [`ports.py:51`](../../Speak-EPUB-1.0.0/core/ports.py#L51)

**Adapter — HTTP & Search**

- Polite _get with UA SpeakEPUB/1.0, jitter and capped backoff retry
  [`_http.py:24`](../../Speak-EPUB-1.0.0/adapters/_http.py#L24)

- Search validates empty/whitespace without network and truncates >300
  [`novelphoenix.py:31`](../../Speak-EPUB-1.0.0/adapters/novelphoenix.py#L31)

- Search parses div.book-item, chapter_count via regex and cover via img src
  [`novelphoenix.py:59`](../../Speak-EPUB-1.0.0/adapters/novelphoenix.py#L59)

- 4xx/5xx/timeout after 2 retries returns [] with log, no raise
  [`novelphoenix.py:42`](../../Speak-EPUB-1.0.0/adapters/novelphoenix.py#L42)

**Adapter — Chapters & Content**

- listChapters validates url, extracts cover og:image fallback img.cover with lock
  [`novelphoenix.py:118`](../../Speak-EPUB-1.0.0/adapters/novelphoenix.py#L118)

- Chapter anchors ul.chapter-list + fallback a[href*=chapter], dedupe and filter noise
  [`novelphoenix.py:149`](../../Speak-EPUB-1.0.0/adapters/novelphoenix.py#L149)

- Dedupe normalizes fragment/query/slash and skips javascript: and short titles
  [`novelphoenix.py:173`](../../Speak-EPUB-1.0.0/adapters/novelphoenix.py#L173)

- fetchChapter isolates via getSelectors else heuristic, strips script/style/nav/aside
  [`novelphoenix.py:200`](../../Speak-EPUB-1.0.0/adapters/novelphoenix.py#L200)

- getSelectors returns div#chapter-content source of truth
  [`novelphoenix.py:269`](../../Speak-EPUB-1.0.0/adapters/novelphoenix.py#L269)

**Core — Aggregator**

- search_all parallel fan-out 5s timeout, dedupe and fault-isolate per adapter
  [`aggregator.py:26`](../../Speak-EPUB-1.0.0/core/aggregator.py#L26)

- Safe search catches BaseException and guards None url/site
  [`aggregator.py:17`](../../Speak-EPUB-1.0.0/core/aggregator.py#L17)

**Tests & Config**

- 29 mocked tests cover search/listChapters/cover/dedupe and aggregator isolation
  [`test_novelphoenix.py:1`](../../Speak-EPUB-1.0.0/tests/test_novelphoenix.py#L1)

- Adapter factory export without pipeline import
  [`__init__.py:3`](../../Speak-EPUB-1.0.0/adapters/__init__.py#L3)

- Requests pin and import-linter contracts kept
  [`requirements.txt:18`](../../Speak-EPUB-1.0.0/requirements.txt#L18)

