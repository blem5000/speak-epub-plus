# Action-Item Triage — manual (Loop module off) — 08-31-2026

All 38 open action items in sprint-status.yaml were verified against the current working tree on 08-31-2026. Epic-3/4 items come from today's retros (sources in the retro docs); epic-1/2 items were re-verified inline for this triage.

## Decisions (human choice)

| D# | Item(s) | Options | Recommendation |
|----|---------|---------|-----------------|
| D1 | epic-1:1 - virtualized windowing | (a) build as new story (react-window); (b) keep deferred; (c) close: cap 100 + Show all is acceptable for <1k lists (deferred 3x) | (c) close - stop re-deferring; revisit only if list performance becomes a real problem |
| D2 | epic-1:2 - _CHAPTER_CACHE | (a) document as canonical (in-memory, query-stripped key, per-run); (b) implement TTL/invalidation; (c) keep-open | (a) document - tiny in-memory cache, TTL is over-engineering |
| D3 | epic-2:6 - lord mock | (a) feature-flag behind env (SPEAK_LORD_MOCK=1); (b) remove entirely; (c) keep-open | (a) flag - keep the offline/demo affordance, remove production-path surprise |
| D4 | epic-2:10 - cover fetch ScraperPort bypass | (a) reconcile spec (accept direct requests fetch with UA, document exception); (b) route cover via ScraperPort; (c) keep-open | (a) reconcile - cover is a single-URL demo fetch; port-bypass cost is not worth the adapter surface |
| D5 | epic-4:4 - 1120px breakpoint | (a) implement 1120 max-w; (b) reconcile spec to lg=1024 (Tailwind default); (c) keep-open | (b) reconcile - 1024 lg is the Tailwind ecosystem default, less special-casing |

## Bundles (buildable now)

| Bundle | Cohesive goal | Items | Owner |
|--------|---------------|-------|-------|
| B1 land-remediation-patch | Commit the verified working-tree remediation and restore a green build+test baseline: fetch cache-hit pipeline fix, DOMPurify in Preview (+tests), core/http replacing the lint-imports violation, remove unused userEvent (npm run build), gate: tsc + vitest + pytest | epic-2:1, 2-3, 2-4 (commit part), 2-5, 2-12; epic-4:10 (DoD gate) | Core+GUI |
| B2 security-hardening | Strengthen Tauri security: set non-null CSP (default-src 'self' + connect-src for sidecar), commit capabilities scoping (shell removed, opener scoped to epub/output), isolate http fallback (localhost:17381) | epic-1:5, epic-2:2 | Security |
| B3 error-code-mapping | Derive HTTP/RPC status from exception code/attributes in core/config.py (372-374, 1914-1918), no message substrings; extend the _http_status pattern from fetch.py to config.py | epic-2:4 (extension part), 2-7 | Core |
| B4 get-epub-status-hardening | getEpubStatus: filter epub candidates by novel slug + surface run_epubcheck failure instead of ok:true | epic-2:8 | Core |
| B5 cache-key-dedupe | One normalize_cache_key + URL validation (fetch.py:31-47 vs config.py:65-82) | epic-2:9 | Core |
| B6 tts-failure-recovery | tts.py failure/recovery: keep_parts deletion success-only + file-survival tests, cleanup on cancellation and zero-byte regeneration, process lesson: failure tests assert invariants | epic-3:1,2,3,4,10 | Core+QA |
| B7 tts-module-decomposition | Split core/tts.py (725 lines, 4 responsibilities) + fix the docstring contract | epic-3:7,8 | Core |
| B8 ffmpeg-escape-verify | Verify apostrophe escaping in concat against a real ffmpeg binary + fix | epic-3:5 | Core |
| B9 speak-duplication | Resolve root vs inner speak.py duplication (canonical + sync-pin test) | epic-3:6 | Scaffold |
| B10 tts-concurrent-lock | Cross-process lock on part writes (resume race, core/tts.py:339) | epic-3:9 | Core |
| B11 qa-verification-matrix | Cross-story pipeline tests (fetch->selectors->filters->buildEpub, corrupt store, multi-novel status, non-contiguous mapping, PL diacritics) + Find/ChapterList verification pins (host guard, cover, skeleton, clamp) | epic-2:11, epic-1:6 | QA |
| B12 i18n-hardening | i18n: wire existing keys (toast.ban/ffmpeg.missing), fix FiltersWindow ternary, route hardcoded strings, chip via filters.chip | epic-4:1,2,3 | GUI |
| B13 dialog-focus-restore | Settings dialog focus-restore on close matching FiltersWindow | epic-4:5 | GUI |
| B14 app-state-unification | A single chapter-status reducer + extract App.tsx orchestration into hooks/components; remove demo token section + legacy-ref stub | epic-4:6,7,8 | GUI |
| B15 frontend-edge-tests | Settings revert/concurrent blur, useFetcher unmount leak + non-sequential done, Queue error+parts | epic-4:9 | QA |

## Skip / blocked

None - every open item is either a buildable bundle or a human decision. (Twenty epic-3/4 items were added in today's retros and are all still open.)

## Suggested sequencing

Run decisions D1-D5 first (none block bundles, but cheap to settle), then bundles by impact: B1 -> B2 -> B3/B5 -> B6 -> B12 -> B14 -> rest. B1 is the cheapest, highest-value item: it commits verified work and restores a green build.

## Decisions resolved (09-02-2026)

| D# | Decision | Effect |
|----|----------|--------|
| D1 | **(c) close** — cap 100 + Show all accepted for <1k lists; stop re-deferring. Revisit only if list performance becomes a real problem. | epic-1-retro-item-1 → done |
| D2 | **(a) document** — `_CHAPTER_CACHE` is canonical: small in-memory cache, query-stripped key, per-run lifetime; TTL judged over-engineering. | epic-1-retro-item-2 → done |
| D3 | **(a) feature-flag** — lord mock search fallback behind env `SPEAK_LORD_MOCK=1`; production path mock-free, offline/demo affordance preserved. | epic-2-retro-item-12 stays open, action narrowed (buildable, fold into a Core bundle) |
| D4 | **(a) reconcile spec** — cover fetch direct `requests` with UA documented in spec-2-3 as an explicit exception (single-URL demo fetch). | epic-2-retro-item-16 → done, spec-2-3 updated |
| D5 | **(b) reconcile spec** — preview breakpoint reconciled to Tailwind `lg` = 1024px; custom 1120px dropped from spec-4-4. No code change. | epic-4-retro-item-32 → done, spec-4-4 updated |

Remaining open items after decisions: D3 build work (item-12) + bundles B2-B15. Suggested next bundle: **B2 security-hardening**.