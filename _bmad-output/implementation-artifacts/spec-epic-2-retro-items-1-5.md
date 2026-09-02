---
title: 'Epic-2 retro items 1-5: GUI/security hardening + core pipeline contract fixes'
type: 'bugfix'
created: '2026-08-31'
status: 'in-review'
review_loop_iteration: 0
baseline_commit: c700be50bd83ee2a750857c46afcb60d893b14cc
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-2-retro-08-31-2026.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The epic-2 retrospective confirmed five fix-now defects: Preview renders unsanitized scraped HTML (XSS in a webview holding broad Tauri capabilities), Tauri capabilities are unscoped (`shell:allow-spawn`, unrestricted `opener:allow-open-path`), the fetch cache-hit path returns naive whole-page text while fresh fetches return selector-isolated content (fetch→clean contract diverges by cache state), retryable classification matches chapter numbers inside URLs (`/chapter/500` retried as 5xx, `/chapter/429` flips the global throttle tier on a 403), and `core/config.py` imports `adapters._http` breaking the machine-enforced `core-no-adapters` contract.

**Approach:** Sanitize both Preview HTML sinks with DOMPurify; scope Tauri capabilities to what the frontend actually uses; route the cache-hit path through the same `resolve_selectors`+`clean_html` pipeline as fresh fetches and drop the repr-poisoning cache fallback; derive HTTP status for retry/throttle decisions from the exception chain (`__cause__` response status) instead of substring matching over messages containing URLs; give Core its own HTTP helper (`core/http.py`) so the config fallback no longer imports an adapter module.

## Boundaries & Constraints

**Always:** Preserve the raw-never-filtered invariant: cache still stores raw HTML (`write_cache` unchanged for the fresh-fetch path); cleaning happens on read. Cache-hit and fresh-fetch paths must return the same `ChapterContent` shape (`html` = isolated body HTML, `text` = isolated text). Politeness tiers and `throttleChanged` semantics stay: only a genuine HTTP 429 may flip the tier to `safe`. `core/http.py` reuses the same politeness values as `adapters/_http.py` (UA `SpeakEPUB/1.0`, timeout 12s, retries 2, backoff min(20, 2*attempt) + jitter 0.2–0.6) so behavior is indistinguishable. All existing tests keep passing (pytest 249, vitest 117) plus the new ones below.

**Ask First:** If removing `shell:*` from capabilities breaks the Rust-side sidecar spawn or `tauri dev` fails to build, HALT and report. If scoping `opener:allow-open-path` to `**/*.epub` + `**/output/**` cannot express the Result card's real open-path usage, HALT with the actual path shape before choosing a broader scope.

**Never:** Do not remove the `tauri_plugin_shell::init()` registration or `@tauri-apps/plugin-shell` dependency (Rust-side spawn may depend on the plugin; only the capability entries change). Do not dedupe `_normalize_cache_key` or URL validation (separate retro item 9). Do not modify adapters' own `_http.py`. Do not touch the `"lord"` mock fallback (item 6) or `getEpubStatus` (item 8). Do not add sanitizer bypasses such as `ALLOW_UNKNOWN_PROTOCOLS`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Cache hit, adapter selectors resolve | `_cache/<sha1>/raw.html` exists, override/default selectors valid | `ChapterContent(html=<isolated body>, text=<isolated text>, title=<h1/h2/h3>)` — same shape as fresh fetch | selector ValueError → retry with `(None, None)` heuristic fallback, never raise |
| Cache hit, no selectors match | cached raw.html, selectors find nothing | falls back to `(None, None)` heuristic clean like the adapter does | empty result still returns ChapterContent, logged |
| 404 on `/chapter/500` | adapter raises AdapterError FETCH_FAILED, `__cause__` = HTTPError(404) | NOT retryable — status error immediately, no throttle emit | maps to LIST_FAILED as today |
| 429 from server | `__cause__` = HTTPError(429) | retryable, tier → safe, `on_throttle("safe", 10000)` once per flip | after max_retries → LIST_FAILED |
| 403 on `/chapter/429` | HTTPError(403) | NOT 429 — no throttleChanged, no safe tier | LIST_FAILED |
| Timeout / connection error | `__cause__` = Timeout or ConnectionError | retryable as today | LIST_FAILED after retries |
| Preview XSS payload | scraped html contains `<img src=x onerror=alert(1)>` | rendered sink contains no `onerror` attribute after sanitize | sanitize never throws |
| Config fallback fetch | no cache, `core/http._get` used | identical response handling as before (`resp.text`), lint-imports green | request failure → LIST_FAILED as today |

</frozen-after-approval>

## Code Map

- `src/components/Preview.tsx` -- the two XSS sinks at :424 and :426 (`dangerouslySetInnerHTML`); component already imports React hooks; add DOMPurify import and wrap both `.slice(0, 20000)` expressions.
- `src/components/Preview.test.tsx` -- 8 existing tests (tabs/focus/debounce/save); add sanitization tests here; mocks live in `src/test/*` setup with `@testing-library/react`.
- `src-tauri/capabilities/default.json` -- permission list; frontend grep shows zero `plugin-shell` usage (sidecar spawned via `std::process` in `src-tauri/src/lib.rs:137`, plugin registered at :198); `opener|open_path` invoked from `src/components/Result.tsx:91` with `result.path` (an `.epub` file path).
- `Speak-EPUB-1.0.0/core/fetch.py` -- `fetch_one(url, adapter, ...)` at :114; cache-hit block :153-185 (naive `get_text`); poisoning fallback :217-219 (`write_cache(url, str(cc))`); retry classification :236-241 (`is_429`/`is_5xx` regex over full message); tier flip + throttle emit at :275-300. `read_cache`/`write_cache`/`cache_key` at :56-84.
- `Speak-EPUB-1.0.0/core/clean.py` -- `resolve_selectors(adapter)` and `clean_html(html, start, end) -> (html, text)`; heuristic fallback = call with `(None, None)`; invalid selector raises `ValueError`.
- `Speak-EPUB-1.0.0/core/config.py` -- previewChapter fallback import at :1245 (`from adapters._http import _get`); context :1233-1252 (raw from cache else fetch, no write).
- `Speak-EPUB-1.0.0/adapters/_http.py` -- reference only (READ-ONLY): `_get` raises `requests.exceptions.HTTPError(..., response=resp)` on HTTP errors and Timeout/ConnectionError otherwise; adapter wraps as `AdapterError(f"FETCH_FAILED: {e}", code="FETCH_FAILED") from e` (`adapters/novelphoenix.py:220`) — so the HTTP status lives on `exc.__cause__.response.status_code`.
- `Speak-EPUB-1.0.0/tests/test_fetch.py`, `tests/test_handle_rpc_preview.py` -- existing suites to extend (fetch cache-hit/retry-classification cases; preview fallback still green).
- `.importlinter` -- contracts: `core-no-adapters` (forbidden core→adapters), `adapters-no-pipeline` forbids adapters→`core.fetch/clean/epub/tts/merge/aggregator/pipeline/config` — a new `core/http` module is NOT forbidden, so adapters could import it later (do not do that now).

## Tasks & Acceptance

**Execution:**
- [x] `src/components/Preview.tsx` -- add `dompurify` import; wrap both `dangerouslySetInnerHTML` sinks with `DOMPurify.sanitize(...)` -- closes the XSS sinks.
- [x] `package.json` -- `npm install dompurify` (v3 ships its own types) -- dependency for the sanitizer.
- [x] `src/components/Preview.test.tsx` -- add tests: onerror payload stripped in both tabs; clean content still renders -- pins the sanitizer.
- [x] `src-tauri/capabilities/default.json` -- remove `shell:default`, `shell:allow-open`, `shell:allow-spawn`; replace bare `opener:allow-open-path` with a scoped entry (`allow`: `**/*.epub`, `**/output`, `**/output/**`) -- capability surface matches actual frontend usage.
- [x] `Speak-EPUB-1.0.0/core/fetch.py` -- rewrite cache-hit block to call `resolve_selectors(adapter)` + `clean_html(cached, sel.start, sel.end)` (ValueError → `(None, None)` fallback), keep title extraction, emit same status/log events; delete the `write_cache(url, str(cc))` else-branch (never cache a non-HTML repr) -- unifies the fetch→clean contract.
- [x] `Speak-EPUB-1.0.0/core/fetch.py` -- add `_http_status(exc)` helper reading `exc.code` and walking `exc.__cause__` chain for `.response.status_code` (Timeout/ConnectionError → timeout); rewrite `is_429`/`is_5xx`/`is_timeout` to use it, substring only on the `code` attribute, never the message -- kills chapter-number false positives.
- [x] `Speak-EPUB-1.0.0/core/http.py` -- new module with `_get(url, timeout=12, retries=2)` mirroring `adapters/_http.py` politeness values -- Core-owned raw fetch for the config fallback.
- [x] `Speak-EPUB-1.0.0/core/config.py` -- replace the `from adapters._http import _get` fallback at :1245 with `from core.http import _get` -- restores `core-no-adapters` green.
- [x] `Speak-EPUB-1.0.0/tests/test_fetch.py` -- add cases from the I/O matrix: cache-hit parity (isolated text, not whole page), poisoned-fallback no longer writes cache, 404-on-chapter-500 not retried, 403-on-chapter-429 no throttle emit, real 429 flips tier once -- pins the contract fixes.

**Acceptance Criteria:**
- Given a cached raw.html containing nav/footer, when `fetch_one` runs, then returned `text` excludes nav/footer content (selector isolation applied), matching a fresh fetch of the same URL.
- Given `npm run lint:imports`, when it runs, then both contracts report KEPT (exit 0).
- Given scraped HTML with an inline event handler, when Preview renders Original or Cleaned tab, then no `onerror`/`onclick` attribute appears in the DOM.
- Given the full existing suites, when `pytest` and `vitest` run, then all pass including the new cases.

## Spec Change Log

<!-- Empty until the first review loopback. -->

## Design Notes

Status derivation must climb the `__cause__` chain because the adapter wraps the transport error: `AdapterError(FETCH_FAILED)` → cause `HTTPError(response=resp)` → `resp.status_code`. Keep substring matching as last resort on the `code` attribute only (`"429" in code`), since `HTTPError` may arrive unwrapped from direct `_http` use. Cache-hit cleaning must reuse the adapter's own selector resolution (`resolve_selectors(adapter)`) so preview-corrected overrides apply identically on resume — that is the whole point of the contract fix.

## Verification

**Commands:**
- `npm run lint:imports` -- expected: `Contracts: 2 kept, 1 broken` becomes `2 kept, 0 broken` (exit 0).
- `Speak-EPUB-1.0.0/venv\Scripts\python.exe -m pytest Speak-EPUB-1.0.0/tests -q` -- expected: 249 + new fetch tests, all pass.
- `npm test` -- expected: 117 + new Preview tests, all pass.
- `npm run build` -- expected: may still fail on the pre-existing TS6133 in `src/App.announcer.test.tsx:3` (retro item 12, out of scope) — do not fix here, but confirm no NEW tsc errors.


