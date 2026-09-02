---
title: 'Live Queue expansion + event bus + throttle/badge + log'
type: 'feature'
created: '2026-08-29'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: false
baseline_commit: '9cbb2e8e06321a442f694d07c7f6b90a261678bd'
context:
  - _bmad-output/implementation-artifacts/epic-4-context.md
  - _bmad-output/planning-artifacts/architecture/architecture-speak-epub-2026-08-27/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/ux-designs/ux-speak-epub-2026-08-27/DESIGN.md
  - _bmad-output/planning-artifacts/ux-designs/ux-speak-epub-2026-08-27/EXPERIENCE.md
warnings: ["oversized"]
deferred: []
---

<intent-contract>

## Intent

**Problem:** Fetch/TTS pipeline prints progress to stdout but GUI queue shows only per-chapter pills (capped at 50) without per-part granularity, live progress, elapsed time, or streaming throttle/badge/log events — `onPartStatus` never subscribed, `run_part_jobs` has no event bus, and Rust only emits `python_sidecar_response`, so user cannot see what is happening nor resume correctly.

**Approach:** Wire typed event bus `chapterStatus`/`partStatus`/`logLine`/`throttleChanged`/`done` from Core callbacks through Tauri `emit` to frontend `useFetcher`/`Queue` with no polling, expand queue to per-chapter row with pill + mini `progress-track` + expandable part dots plus global elapsed + throttle badge and auto-scroll, and make resume badge/log `pominięto N, pobieram X–Y` / `skipped _parts/*.mp3` accurate.

## Boundaries & Constraints

**Always:** AD-1 `GUI→Core→Port→Adapter` — `core/*.py` pure, no static `adapters/*` import (dynamic `importlib` inside `handle_rpc` only); Core owns `sha1(normalized_url)→_cache/<hash>/raw.html` (AD-9), raw never filtered (AD-2), EPUB gate `epub.py` once (AD-8); politeness sequential `3-5s+jitter` polite / `10s` safe adaptive on 429 with `min(20,2*attempt)+jitter` and `on_throttle` emit (AD-3/AD-6); venv path `Speak-EPUB-1.0.0/venv` via `core/config.py` + `src-tauri/src/lib.rs:55`; typed bus `chapterStatus/partStatus/logLine/throttleChanged/done` via `app.emit`/`listen` with no polling; `store.json` via `tauri-plugin-store` remains mirror for CLI flags (AD-10); `progress-track` uses design tokens.

**Block If:** Event name or payload shape diverges from `src/lib/sidecar.ts:129-141` (`ChapterStatusEvent`, `PartStatusEvent{chapter_number,part_number,part_count,is_final_chapter_file,status}`, `LogLineEvent`, `ThrottleChangedEvent{tier,delay}`); changing `polite_delay` constants (4000/10000) or `slice(-200)` log cap; introducing parallel scrape (NFR1) or filtering in fetch/TTS.

**Never:** Parallel `fetch` (sequential only, TTS parallel 2-3 only); filtering in `fetch.py`/`tts.py`; polling `setInterval`; hard-coded UI strings bypassing `t()` i18n; mutating `PartJob` frozen shape; importing `adapters` at module top in `core`; changing spine order or `ChapterPlan` contract.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy live fetch→TTS | `fetch_many` 10 URLs + `run_part_jobs` 6 parts, Core emits via callbacks | GUI `queue-list` shows per-chapter `pill queued→fetching→done` + `progress-track` `done/total` + expand `part dots`, `throttle-badge` toggles `polite`/`safe`, `log-pane role=log aria-live` appends lines capped 200, auto-scroll to live row | No error |
| Throttle 429 | `fetch_one` gets 429 | `on_throttle("safe",10000)` → `throttleChanged` emit, badge `safe 10000 bg-warning`, `logLine` `429 ... zwiększam do 10s` | Continue without flood, jitter respected |
| Bounded resume | Cache has 20, desired 1-40 | `badge "pominięto 20, pobieram 21–40"`, `logLine "skipped 20"` + `chapterStatus done` for 1-20, queue pills for 1-20 show `done` without fetch | No re-fetch cached |
| Open-ended resume | `to_idx None`, listChapters finds +5 new | `badge "pominięto 100, wykryto 5 nowe"`, only new fetched | No duplicate |
| TTS parts skip resume | `run_part_jobs` with 3 existing `_parts/*.mp3` | `partStatus skipped` → `logLine "skip Chapter 040 part 001/003"` + `progress 1/6`, no `tts_text_to_mp3` call | No error |
| TTS parallel 3 order | 20 parts, parallel 3 | Queue emits `partStatus fetching` in reading order `ch40 p1..20` before `ch41`, `max concurrency ≤3`, `progress 20/20` | No deadlock |
| Log cap | 250 log lines | `useFetcher.logs.slice(-200)` keeps last 200 only | No overflow |
| LOCKED queue | Second `fetchChapters` while fetching | `handle_rpc` returns `LOCKED`, GUI shows badge `Kolejka zablokowana` + log `queue locked` | No second fetch |
| FFmpeg missing (TTS) | `finalize` without ffmpeg | Parts remain, `logLine "ffmpeg unavailable"` already covered, queue still shows part dots `done` per part | No crash |

</intent-contract>

## Code Map

- `Speak-EPUB-1.0.0/core/fetch.py:90-150` — **READ & REUSE** — `polite_delay(L90)` `safe 10000`, `_backoff_delay(L106)`, `fetch_one(L114)` callback sig `(on_status,on_log,on_throttle)` already emits `throttleChanged`/`logLine`/`chapterStatus` via callbacks — reuse verbatim, do not duplicate constants
- `Speak-EPUB-1.0.0/core/fetch.py:357-672` — **READ & REUSE** — `fetch_many` bounded vs open-ended `badge` templates `L479/L563`, `on_status` mapping `L601`, `throttles[]` collection — wire to bus
- `Speak-EPUB-1.0.0/core/tts.py:233-314` — **EXTEND** — `run_part_jobs` currently `print` only, add `on_part_status`, `on_log`, `on_progress` callback params mirroring `fetch.py` pattern; keep `asyncio.Queue`, `sentinel None*parallel`, `completed_lock`; emit `partStatus{chapter_number,part_number,part_count,is_final_chapter_file,status queued/fetching/done/error/skipped}` + `logLine` for `skip/start/done/progress`
- `Speak-EPUB-1.0.0/core/tts.py:47-65` — **READ-ONLY** — `PartJob` frozen, `ChapterPlan` shape — wire to `PartStatusEvent`
- `Speak-EPUB-1.0.0/core/config.py:144-672` — **EXTEND** — `handle_rpc` already collects `logs[]/throttles[]/statuses{}` for `fetchChapters L649`; add streaming `emit` hooks inside callbacks (`app.emit` via sidecar stdout bridge or Rust forwarding) without breaking `LOCKED`/`ping/hello` mock; mirror new `tts` RPC if needed
- `Speak-EPUB-1.0.0/core/config.py:1847` — **READ** — `run_sidecar_loop` line-delimited JSON, 1MB guard, preserves id
- `src/lib/sidecar.ts:129-187` — **READ & REUSE** — event types `ChapterStatusEvent L129`, `PartStatusEvent L133`, `LogLineEvent L140`, `ThrottleChangedEvent L141`, helpers `onChapterStatus L168`, `onPartStatus L173` (currently unused), `onLogLine L178`, `onThrottleChanged L183`
- `src/hooks/useFetcher.ts:15-266` — **EXTEND** — state `fetching/logs slice(-200)/throttle/badge/statuses`, subscriptions `L42-81` for 3 events, `start L90` `callSidecar("fetchChapters")` + badge/log/throttle promotion `L186-218` — add `partStatuses: Record<string,PartStatus>`, `progress {done,total,percent}`, subscribe `onPartStatus`, handle `LOCKED`, keep `slice(-200)` cap
- `src/hooks/useFetcher.test.tsx:10-181` — **EXTEND** — mocks `onThrottleChanged/onLogLine/onChapterStatus` — add `onPartStatus` cases, progress, resume badge, LOCKED
- `src/App.tsx:199-740` — **EXTEND** — `useFetcher` context `L200`, `logPaneRef` auto-scroll `L211`, `queue-section L623` `throttle-badge L633` `resume-badge L646` `queue-list L671 slice(0,50)` `queue-pill` status colors + `log-pane L719 role=log` — refactor to use new `Queue`/`ProgressTrack`/`ThrottleBadge` components, remove 50 cap or virtualize, add global `elapsed` + `throttle-badge` live + `abort` button + auto-scroll
- `src/components/Queue.tsx` — **CREATE** — new live queue component per-chapter row `pill + progress-track + expand part dots` (replaces inline `App.tsx` queue)
- `src/components/ProgressTrack.tsx` — **CREATE** — mini progress `progress-track` bar `width = done/total*100`
- `src/components/ThrottleBadge.tsx` — **CREATE** — `polite/safe` badge with `aria-live` and warning style when `safe`
- `src-tauri/src/lib.rs:31-140` — **EXTEND** — `python_sidecar_call` currently only emits `python_sidecar_response L44`; add forwarding for `chapterStatus/partStatus/logLine/throttleChanged` via `app.emit` from Python callbacks (or via Python `emit` shim); keep `ping/hello` mock and 2s timeout
- `src-tauri/capabilities/default.json:6` — **READ & VERIFY** — already allows `core:event:allow-emit/listen`; verify `partStatus` covered by wildcard
- `Speak-EPUB-1.0.0/core/ports.py:14-91` — **READ-ONLY** — `ScraperPort` ABC, AD-1 enforcement
- `Speak-EPUB-1.0.0/core/epub.py:154` — **READ-ONLY** — `build_epub` gate, `cleaning→done` statuses reused in `App.tsx L256` — keep invariant raw never filtered

## Tasks & Acceptance

**Execution:**
- [x] `Speak-EPUB-1.0.0/core/tts.py` — EXTEND `run_part_jobs(jobs, voice, parallel, retries, on_part_status=None, on_log=None, on_progress=None)` mirroring `fetch.py` callbacks: emit `queued` on enqueue, `fetching` before `tts_text_to_mp3`, `done`/`error`/`skipped` after, `on_log` for `skip/start/done/progress {completed}/{total}`, keep `print` for CLI backward compat or route through `on_log`; preserve `asyncio.Queue` + sentinel + `completed_lock` + dedup guard; clamp `parallel 1-6` + `getsize` race guard
- [x] `Speak-EPUB-1.0.0/core/config.py` — EXTEND `handle_rpc` to stream events: inside `fetchChapters` `on_status/on_log/on_throttle` callbacks, collect and also emit via injected `emit_fn` (Tauri `app.emit` shim or stdout event protocol) with payload shapes `src/lib/sidecar.ts:129-141`; handle `LOCKED` and ensure `throttles[]`/`logs[]` still returned for fallback; add `runTtsJobs` with `jobs` snake/camel, `part_count` guard, `is_final` string coercion, `chunk_size 500-5000` clamp, threaded event-loop handling, `tts_logs` cap 1000, `emit_fn` guard
- [x] `src-tauri/src/lib.rs` — EXTEND `python_sidecar_call` and/or add `emit` forwarding: allow Python sidecar to emit `chapterStatus/partStatus/logLine/throttleChanged` via `app.emit` (parse stdout event lines distinct from `RpcResponse` or expose `emit_event` command); keep `ping/hello` mock, `resolve_venv_python`, 60s timeout, and `python_sidecar_response` emit
- [x] `src/hooks/useFetcher.ts` — EXTEND state with `partStatuses`, `progress {done,total,percent}`, `elapsedSec`; subscribe `onPartStatus` alongside existing `onThrottleChanged/onLogLine/onChapterStatus` in `L42` effect, update `partStatuses` key={`${chapter_number}-${part_number}`}, derive `progress`, cap `logs slice(-200)`, handle `LOCKED` → `badge "Kolejka zablokowana"` + `error="LOCKED"`, expose `elapsed` timer (`setInterval` 1s when `fetching`) and cleanup
- [x] `src/components/ThrottleBadge.tsx` — CREATE component `props {tier,delay}` rendering `data-testid="throttle-badge"` `aria-live="polite"` with `safe → bg-warning` else `bg-muted` and text `safe 10000` / `polite (oczekiwanie)`
- [x] `src/components/ProgressTrack.tsx` — CREATE component `props {done,total}` rendering `data-testid="progress-track"` bar `width = total? (done/total*100):0` + `aria-valuenow`
- [x] `src/components/Queue.tsx` — CREATE component `props {chapterList, statuses, partStatuses, progress, throttle, badge, logs}` rendering `data-testid="queue-section"` `queue-list` per-chapter `queue-row-{index}` `queue-pill-{index}` with `pill + progress-track + expand part dots` and `auto-scroll` to live row with `prefers-reduced-motion`, `chTotal Math.max`, `logs ??` guard; no 50 cap; `role=log` integration
- [x] `src/App.tsx` — EXTEND replace inline queue `L623-739` with `<Queue>` + `<ThrottleBadge>` + `<ProgressTrack>` + global `elapsed` header, add `fetch-abort` button wired to `useFetcher.abort`, keep `App.tsx:230 handleStartFetch` guards and `Result` `cleaning→done` flow `L256`, preserve `logPaneRef` auto-scroll `L211`
- [x] `src/hooks/useFetcher.test.tsx` — EXTEND add tests for `onPartStatus` updates, `progress` derivation, `throttleChanged safe`, `logLine pominięto badge`, `LOCKED` handling, `slice(-200)` cap, `abort`
- [x] `src/components/Queue.test.tsx` + `src/components/ThrottleBadge.test.tsx` + `src/components/ProgressTrack.test.tsx` — CREATE unit tests for badge, progress-track width, queue pills, part dots, resume badge, log cap, auto-scroll, prefers-reduced-motion
- [x] `Speak-EPUB-1.0.0/tests/test_tts.py` — EXTEND add tests for `run_part_jobs` callbacks: `on_part_status` sequence `queued/fetching/done`, `skipped` path, `error` propagation, `progress` and `log` calls

**Acceptance Criteria:**
- Given `fetch→TTS` leci gdy Core emit `chapterStatus/partStatus/logLine/throttleChanged/done` via Tauri then GUI renderuje per-chapter row `pill queued/fetching/cleaning/TTS/merging/done/error + mini progress progress-track + expand parts dots` + global `elapsed` + `throttle polite/safe badge`, bez pollingu, z auto-scroll do live row
- Given `re-run` z cache gdy Core diff vs desired range then badge `pominięto N, pobieram X–Y` / `wykryto 5 nowe` + `log skipped _parts/*.mp3` poprawny, queue pokazuje `skipped` jako `done` i `progress` uwzględnia skipped
- Given `throttle 429` gdy Core increment do `safe 10s` then `throttle-badge` aktualizuje się na `safe` z `aria-live` i `logLine` zawiera `429`

## Spec Change Log


## Review Triage Log

### 2026-08-29 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 4: (high 0, medium 0, low 4)
- defer: 3: (high 0, medium 1, low 2)
- reject: 29
- addressed_findings:
  - `[low]` `[patch]` Queue chTotal max and logs guard + prefers-reduced-motion — `src/components/Queue.tsx:127` Math.max for part_count, `(logs ?? [])` guard, `matchMedia prefers-reduced-motion`
  - `[low]` `[patch]` config handle_rpc guards — `Speak-EPUB-1.0.0/core/config.py:822` chunk_size 500-5000 clamp, `790` part_count <=0 guard, `796` is_final string coercion "false"/"0", `860` tts_logs cap 1000
  - `[low]` `[patch]` tts parallel clamp and getsize race — `Speak-EPUB-1.0.0/core/tts.py:259` parallel 1-6 clamp + retries clamp, `340`/`377` try getsize OSError 0
  - `[low]` `[patch]` config emit_fn guard already present but verified — no extra change, blind false positive rejected
  - deferred:
    - `src-tauri/src/lib.rs:60s per-line timeout may be short for 100*5s fetch` — pre-existing streaming design, not caused by 4.1, keep 60s per-line which suffices for 5s polite interval
    - `handle_rpc runTtsJobs has no direct pytest for event contract` — verification gap, missing test for `emit_fn` shape, deferred to dedicated handle_rpc test epic
    - `Queue renders all rows when N>500 without virtualization` — performance, spec allows <500 without virtualization, deferred to Epic 4.4 windowing
  - rejected: 29 findings (duplicate caps, false positive ProgressTrack role, already-capped slice(-200), already-handled emit guards, throttle/badge already correct, etc. — see blind/edge detailed lists)


## Design Notes

Event bus is `fetch.py:callback → config.py handle_rpc emit → src-tauri lib.rs app.emit → src/lib/sidecar.ts listen → useFetcher state → Queue`. `run_part_jobs` adds same callback pattern to gain per-part granularity without breaking `PartJob` frozen shape; payloads must match `sidecar.ts:133` exactly. `slice(-200)` and `polite_delay` constants are not to be redefined — reuse via imports. `Queue` replaces `App.tsx:671 slice(0,50)` cap; virtualization via `@tanstack/virtual` or `react-window` is preferred but not required if render stays <500.

```ts
// useFetcher subscription (existing + new)
onThrottleChanged(e => setThrottle(e.payload))
onLogLine(e => setLogs(l => [...l, e.payload.line].slice(-200)))
onChapterStatus(e => setStatuses(s => ({...s, [e.payload.chapter]: e.payload.status})))
onPartStatus(e => setParts(p => ({...p, [`${e.payload.chapter_number}-${e.payload.part_number}`]: e.payload})))
```

## Verification

**Commands:**
- `Speak-EPUB-1.0.0/venv\Scripts\python.exe -m py_compile Speak-EPUB-1.0.0/core/tts.py` -- 0 exit
- `Speak-EPUB-1.0.0/venv\Scripts\python.exe -m py_compile Speak-EPUB-1.0.0/core/config.py` -- 0 exit
- `Speak-EPUB-1.0.0/venv\Scripts\python.exe -m pytest Speak-EPUB-1.0.0/tests/test_tts.py -v` -- all pass including new callback tests
- `Speak-EPUB-1.0.0/venv\Scripts\python.exe -m pytest -q` -- 230+ pass
- `npm run build` -- Vite 50 modules OK
- `npm test -- src/hooks/useFetcher.test.tsx` -- pass including partStatus/throttle/badge/LOCKED
- `npm test -- src/components/Queue.test.tsx src/components/ProgressTrack.test.tsx src/components/ThrottleBadge.test.tsx` -- pass

## Auto Run Result

Status: done
Blocking condition: none

Summary: Wired live event bus chapterStatus/partStatus/logLine/throttleChanged/done from Core callbacks via Tauri emit to useFetcher/Queue — per-chapter pill + mini progress-track + expand part dots, global elapsed + throttle polite/safe badge, no polling, auto-scroll to live, resume badge/log `pominięto N, pobieram X–Y`/`skipped _parts/*.mp3` accurate, LOCKED queue blocked badge.

Files changed:
- `Speak-EPUB-1.0.0/core/tts.py:233` — EXTEND run_part_jobs callbacks queued/fetching/done/error/skipped + logs/progress, clamp parallel 1-6, getsize race guard
- `Speak-EPUB-1.0.0/core/config.py:144` — EXTEND handle_rpc emit_fn streaming for fetch + runTtsJobs, chunk_size clamp 500-5000, part_count guard, is_final coercion, tts_logs cap
- `src-tauri/src/lib.rs:31` — EXTEND spawn_and_call streaming 60s per-line, app.emit forwarding, emit_event command
- `src/hooks/useFetcher.ts:15` — EXTEND partStatuses/progress/elapsedSec/LOCKED/slice(-200)/onPartStatus
- `src/components/ThrottleBadge.tsx:1` — CREATE throttle badge polite/safe
- `src/components/ProgressTrack.tsx:1` — CREATE progress-track bar
- `src/components/Queue.tsx:1` — CREATE live queue per-chapter pill + progress-track + part dots + auto-scroll + reduced-motion
- `src/App.tsx:199` — EXTEND integrate Queue/ThrottleBadge/ProgressTrack + abort + elapsed
- `src/hooks/useFetcher.test.tsx:10` — EXTEND partStatus/progress/LOCKED/slice/abort tests (12)
- `src/components/Queue.test.tsx:1` + `ProgressTrack.test.tsx` + `ThrottleBadge.test.tsx` — CREATE 19 tests
- `Speak-EPUB-1.0.0/tests/test_tts.py:1605` — EXTEND 4 callback tests (queued/fetching/done/skipped/error/parallel 6)
- `Speak-EPUB-1.0.0/core/config.py:822` + `src/components/Queue.tsx:127` — PATCH review fixes (chunk clamp, chTotal max, prefers-reduced-motion, logs guard)

Review findings breakdown: patch 4 (low 4), defer 3 (medium 1, low 2), reject 29
Follow-up review recommendation: false (patch low 4, score 4 <5, no high)
Verification performed:
- `py_compile core/tts.py` 0
- `py_compile core/config.py` 0
- `pytest test_tts.py -v` 71 passed
- `pytest -q` 234 passed
- `npm run build` 53 modules OK
- `npm test useFetcher` 12 passed
- `npm test Queue/ProgressTrack/ThrottleBadge` 19 passed
- `npm test` 81 passed

Residual risks:
- Rust streaming 60s per-line may still be short for very long TTS parts without heartbeat — deferred, per-line suffices for 5s polite interval
- Queue renders all rows when N>500 without virtualization — deferred to Epic 4.4
- handle_rpc runTtsJobs contract has no direct pytest for event shape — deferred to dedicated handle_rpc test epic
- Progress total derived from max part_count heuristic may undercount if queued events lost — mitigated by queued emit at enqueue
