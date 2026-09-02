---
title: 'B1 Land Remediation Patch — commit verified remediation + restore green build'
type: 'bugfix'
created: '08-31-2026'
status: 'done'
baseline_commit: c700be50bd83ee2a750857c46afcb60d893b14cc
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent - do not modify unless human renegotiates">

## Intent

**Problem:** Six epic-2 retro action items (Preview XSS, cache-hit clean pipeline, retryable classification from exception attributes, lint-imports violation, npm build broken) plus Tauri capability scoping are fixed in the working tree but uncommitted, and `npm run build` fails on an unused import (TS6133). The fixes risk being lost and the repo has no green build baseline.

**Approach:** Verify the pending working-tree remediation against its stated intent, fix the single build breaker (remove unused `userEvent` import), run the full gate (`npm run build`, vitest, pytest, lint-imports), and commit the code remediation as one patch (B1), with today's retro artifacts (retro docs + sprint-status) in a separate `chore(retro)` commit.

## Boundaries & Constraints

**Always:**
- Run Python tests only via `Speak-EPUB-1.0.0/venv/Scripts/python.exe`; frontend via `npm` scripts. Never use bare `python`.
- Do not alter the behavior of the pending verified changes - this is a land-and-green run, not re-implementation.
- Keep the commit split: one code patch (B1) + one artifacts patch (`chore(retro)`).
- Do not commit tooling dirs (`.cline/`) or `uv.lock` without express approval.
- Scope is exactly epic-2 retro items 1, 3, 4, 5, 12 + epic-4:10 (gate) + in-tree capability scoping.

**Ask First:**
- Whether today's retro artifacts (epic-3/4 retro docs, sprint-status.yaml updated, action-item-triage) go into the separate `chore(retro)` commit or stay uncommitted.
- Whether the in-tree capability scoping belongs in the B1 patch (recommend: yes - small verified security remediation).

**Never:**
- Do not implement B2-B15 bundles, virtualization (react-window), edge-tts/ffmpeg behavior changes, or any new feature.
- Do not commit `venv/`, `node_modules/`, `.cline/`, `uv.lock`.

</frozen-after-approval>

## Code Map

- `Speak-EPUB-1.0.0/core/fetch.py` -- cache-hit now runs `resolve_selectors`+`clean_html` (223-243), `_http_status()` climbs `__cause__` for `.response.status_code`/Timeout (111-153), `_retry_class()` (156-165), empty-html no cache write (289-294); all verified in tree.
- `Speak-EPUB-1.0.0/core/config.py` -- import swap `adapters._http` to `core.http` (~1246-1252), the lint-imports fix.
- `Speak-EPUB-1.0.0/core/http.py` (NEW, untracked) -- Core-owned polite HTTP helper mirroring adapters/_http.py politeness.
- `Speak-EPUB-1.0.0/tests/test_fetch.py` -- +152 lines: cache-hit selector-isolation parity, empty-html no-cache, `_http_status` cause-chain matrix, fetch_many tier-flip matrix.
- `Speak-EPUB-1.0.0/tests/test_handle_rpc_preview.py` -- patched to `core.http._get`.
- `src/components/Preview.tsx` -- DOMPurify.sanitize on both sinks (425, 427); import at :2.
- `src/components/Preview.test.tsx` -- +3 sanitization tests (onerror/onclick stripped, content survives).
- `src/components/App.announcer.test.tsx` -- **line 3 unused `import userEvent`** (TS6133; the build fix sits here).
- `src-tauri/capabilities/default.json` -- shell permissions removed, opener scoped to `**/*.epub`, `**/output`.
- `package.json` -- added `dompurify` dependency.
- `Speak-EPUB-1.0.0/tests/test_http.py` -- **NEW (review patch)** -- pins `core/http._get` behavior: polite UA header, timeout coercion, 429/5xx/other-4xx/timeout retry counts, exhausted-retry `HTTPError` with `.response` attached, invalid-URL ValueError without network.

## Tasks & Acceptance

**Execution:**
- [x] `git diff` + read of listed files -- verify working-tree remediation matches the Code Map (no surprise hunks).
- [x] `src/components/App.announcer.test.tsx` -- remove the unused `userEvent` import (line 3) -- unblocks `tsc` (TS6133).
- [x] `package.json` (no edit needed) -- confirm `dompurify` present in dependencies.
- [x] Root -- run `npm run build` -- expected exit 0 (tsc + vite).
- [x] Root -- run `npm test` (vitest) -- expected all suites green.
- [x] `Speak-EPUB-1.0.0/venv/Scripts/python.exe -m pytest Speak-EPUB-1.0.0/tests` -- expected all green.
- [x] `npm run lint:imports` -- expected "Contracts ... 0 broken".
- [x] Stage + commit: B1 code patch (code + tests + package.json/lock + capabilities) with a dedicated message; then a separate `chore(retro)` commit with retro docs + sprint-status.
- [x] Verify final `git status --short` reflects the agreed exclusions only.

**Acceptance Criteria:**
- Given B1 files, when `npm run build` runs, then it exits 0 (no TS6133).
- Given working-tree remediation, when vitest + pytest run, then all tests pass.
- Given core-no-adapter contract, when `npm run lint:imports` runs, then "0 broken".
- Given a cache-hit chapter with selectors, when `fetch_one` returns, then html/text went through `resolve_selectors`+`clean_html` (parity with fresh fetch, asserted by a test).
- Given an XSS payload in preview, when rendered in either tab, then `onerror`/`onclick` are stripped (Preview.test).

## Spec Change Log

## Suggested Review Order

**Cache-hit clean pipeline (retro item: cache-hit clean pipeline)**

- Entry point: cache hits now flow through the same resolve_selectors + clean_html pipeline as fresh fetches (AD-2 parity)
  [`fetch.py:223`](../../Speak-EPUB-1.0.0/core/fetch.py#L223)

- Empty html never poisons the cache on write
  [`fetch.py:289`](../../Speak-EPUB-1.0.0/core/fetch.py#L289)

- Parity + no-cache-write behavior pinned by tests
  [`test_fetch.py:1`](../../Speak-EPUB-1.0.0/tests/test_fetch.py#L1)

**Retryable classification from exception attributes (retro item)**

- Status derivation climbs the __cause__ chain; never substring-matches str(exc) (URL digits)
  [`fetch.py:111`](../../Speak-EPUB-1.0.0/core/fetch.py#L111)

- (is_429, is_5xx, is_timeout) classifier used by fetch_one/fetch_many tier flips
  [`fetch.py:156`](../../Speak-EPUB-1.0.0/core/fetch.py#L156)

**Core-owned polite HTTP helper (AD-1 lint-imports fix)**

- New core/http.py mirrors adapters/_http.py politeness (UA, 12s, retries 2, backoff) so core no longer imports an adapter
  [`http.py:25`](../../Speak-EPUB-1.0.0/core/http.py#L25)

- previewChapter no-cache fallback rewired to core.http._get
  [`config.py:1246`](../../Speak-EPUB-1.0.0/core/config.py#L1246)

- NEW (review patch): pins the real _get body — UA header, retry counts, HTTPError shape, coercion
  [`test_http.py:1`](../../Speak-EPUB-1.0.0/tests/test_http.py#L1)

**Preview XSS sanitization (retro item)**

- DOMPurify.sanitize on both dangerouslySetInnerHTML sinks (Original + Cleaned tabs)
  [`Preview.tsx:425`](../../src/components/Preview.tsx#L425)

- Sanitization tests: onerror/onclick stripped, clean content survives
  [`Preview.test.tsx:165`](../../src/components/Preview.test.tsx#L165)

**Tauri capability scoping (in-tree remediation)**

- Shell permissions removed; opener scoped to **/*.epub + output
  [`default.json:12`](../../src-tauri/capabilities/default.json#L12)

- Build blocker removed: unused userEvent import (TS6133)
  [`App.announcer.test.tsx:1`](../../src/App.announcer.test.tsx#L1)

**Peripherals**

- dompurify dependency added
  [`package.json:18`](../../package.json#L18)

- Review patch: duplicate review_loop_iteration frontmatter key removed
  [`spec-2-3-filtry-plain-regex-na-etapie-epub-build.md:8`](spec-2-3-filtry-plain-regex-na-etapie-epub-build.md#L8)


- **09-02-2026 (review, iteration 1):** Three reviewer layers (blind-hunter, edge-case-hunter, verification-gap) ran over the landed B1 diff. Patches applied: (1) added `tests/test_http.py` — verification-gap finding that `core/http.py` behavior was pinned by zero tests (behavior had moved from tested `adapters/_http.py` to an untested module; now mirrors the `test_novelphoenix.py` mocking approach); (2) removed duplicate `review_loop_iteration: 0` frontmatter key in `spec-2-3-*.md`. Deferred (recorded in `deferred-work.md`): dead `plugin:shell|open` fallback in `Result.tsx` + opener allow-list policy question; dead `@tauri-apps/plugin-shell` dependency; capability-scoping regression test; `core/http.py` retry-all-4xx policy divergence; backoff-formula triplication; cache-hit isolation-failure fallback asymmetry (`html`→raw cached, `text`→"" — logged "cache-hit isolation empty"). Known-bad state avoided: auto-editing verified B1 behavior during a land-and-green review. KEEP: cache-hit clean-pipeline behavior, `_http_status` cause-chain matrix, capability scoping — all verified by the green gate, do not re-derive.

## Design Notes

## Verification

**Commands:**
- `npm run build` (repo root) -- expected: exit 0
- `npm test` (repo root) -- expected: all vitest suites pass
- `Speak-EPUB-1.0.0/venv/Scripts/python.exe -m pytest Speak-EPUB-1.0.0/tests` -- expected: all pass
- `npm run lint:imports` -- expected: "Contracts ... 0 broken"
- `git status --short` -- expected: clean except approved exclusions

**Results (09-02-2026, post-review-patch):**
- `npm run build` → exit 0
- `npm test` → 17 files / 120 tests passed
- pytest (venv) → 270 passed
- `npm run lint:imports` → "Contracts: 2 kept, 0 broken"
- `git status --short` → clean except `?? .cline/`, `?? uv.lock` (approved exclusions)