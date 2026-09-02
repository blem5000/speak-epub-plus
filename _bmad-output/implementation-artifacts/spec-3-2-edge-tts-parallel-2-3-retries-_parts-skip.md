---
title: 'Edge TTS + parallel 2–3 + retries + _parts skip'
type: 'feature'
created: '2026-08-28'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true
baseline_commit: '5b0433530ff7d866966a59c99ab5a43cbb4ca4ff'
context:
  - _bmad-output/planning-artifacts/architecture/architecture-speak-epub-2026-08-27/ARCHITECTURE-SPINE.md
  - _bmad-output/implementation-artifacts/epic-3-context.md
  - _bmad-output/planning-artifacts/epics.md
warnings: []
deferred:
  - summary: >-
      No timeout on edge_tts Communicate.save — worker can hang indefinitely
    evidence: |-
      blind hunter: Communicate.save has no asyncio.wait_for timeout; single hung stream blocks queue.join forever
    location: >-
      Speak-EPUB-1.0.0/core/tts.py:209
    severity: medium
  - summary: >-
      Retry backoff linear without jitter — thundering herd on throttling
    evidence: |-
      blind hunter: wait = min(20,2*attempt) linear, no jitter; parallel 2-3 will retry simultaneously and retrigger 429
    location: >-
      Speak-EPUB-1.0.0/core/tts.py:215
    severity: low
  - summary: >-
      Structured logging missing — prints outside lock interleave, no logger/ETA
    evidence: |-
      blind hunter: retry and progress prints via bare print, no logger, no quiet flag, lock only for completed counter
    location: >-
      Speak-EPUB-1.0.0/core/tts.py:216
    severity: low
  - summary: >-
      Parallel validation only at CLI, core assumes parallel>=1
    evidence: |-
      edge hunter: parallel 0/negative/None would raise TypeError or hang; spec says core assumes >=1, CLI guards 1..6 warning, but core has no guard
    location: >-
      Speak-EPUB-1.0.0/core/tts.py:238
    severity: medium
  - summary: >-
      Duplicate delegation via copy in speak.py and Speak-EPUB-1.0.0/speak.py
    evidence: |-
      blind hunter: two speak.py files delegated via copy, drift risk, no single import path or deprecation
    location: >-
      speak.py:60
    severity: medium
---

<intent-contract>

## Intent

**Problem:** Po ratyfikacji chunkingu `core/tts.py` (3.1) wykonanie TTS nadal mieszka tylko w `Speak-EPUB-1.0.0/speak.py` — brak Core-owned `tts_text_to_mp3`/`run_part_jobs` z deterministycznym globalnym parallel 2–3 i 5 retries `min(20,2*attempt)` oraz brak wiarygodnego resume `exists(_parts/*.mp3)` w Core, więc re-run nie jest wznawialny a throttling Edge (429) nie ma backoffu z logiem.

**Approach:** Ratyfikować brownfield `speak.py:116 tts_text_to_mp3` + `speak.py:207 run_part_jobs` do `core/tts.py` jako Core-owned single source: przenieść `tts_text_to_mp3(text,output_path,voice,retries=5)` z pętlą `for attempt in 1..retries` `edge_tts.Communicate(text,voice).save` + `min(20,2*attempt)` sleep + log `retry 1/4 dla part_XXX.mp3`, oraz `run_part_jobs(jobs,voice,parallel,retries)` z globalną `asyncio.Queue` reading-order `ch40 p1..20` przed `ch41`, workerami `parallel` (2-3) `queue.put(None)` sentinelami, skip `if exists(output_path)` z logiem `skip`, `completed/total` progress; delegować `speak.py` do `core.tts`.

## Boundaries & Constraints

**Always:** `GUI→Core→Port→Adapter` AD-1 — `core/tts.py` rozszerzony, bez `adapters/*` imports; `speak.py` deleguje do `core.tts.tts_text_to_mp3`/`run_part_jobs` (nie duplikuje); `PartJob` frozen z 3.1, chunk `3500` AD-8; retry `5` `min(20,2*attempt)` jak `speak.py:127` `min(20,2*attempt)`; parallel `2-3` global queue nie per-chapter — `queue: asyncio.Queue[Optional[PartJob]]` wypełniona `for job in jobs: put_nowait(job)` potem `for _ in range(parallel): put_nowait(None)` jak `speak.py:212-217`; worker `while True: job=await queue.get(); if job is None: task_done/break` jak `speak.py:224-229`; skip `if os.path.exists(job.output_path): print skip + size_kb` jak `speak.py:232-237` oraz `build_generation_plan` guard już w 3.1; `edge-tts==7.2.8` pinned w `requirements.txt`; `parallel` sprawdzany `1..6` warning `>6` jak `speak.py:483-494`; `retries` `>=1` jak `speak.py:596`; log `retry {attempt}/{retries-1} dla {name}: {e}` (spec PL `dla`, impl dotąd `for` — zachować istniejący `for` aby nie psuć testów, ale zaakceptować oba w testach case-insensitive) + `worker {id}: start/skip/done Chapter {num:03d} part {p:03d}/{c:03d}` + `progress: {completed}/{total}` jak `speak.py:344-362`; `core/tts.py` nie dotyka `FFmpeg`/`epub`/`filters`.

**Block If:** Zmiana `parallel` poza `1..6` bez WARNING, `retries` poza `1..20` bez guard, zmiana retry backoff z `min(20,2*attempt)` na inny wzór, dodanie parallel scrape (NFR1 zakaz), zmiana `edge-tts` API na inny silnik, modyfikacja `split_text_for_tts`/`PartJob`/`build_generation_plan` (należy do 3.1), dodanie `FFmpeg` merge/M4B (należy do 3.3), zmiana naming `part{03d}`.

**Never:** Parallel fetch (NFR1); filtrowanie w `tts` (AD-2); `adapters` import w `core/tts`; mutacja `PartJob`; dodanie UI `Result`/`Filters`/`Queue` GUI (należy do 4.x); zmiana spine order 1..N; dodanie Sync `requests` w TTS.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy queue 20 parallel 3 | `jobs = build_generation_plan( [(40,"C40","a"*4000*10)], out, 3500) → 20 PartJob` | `run_part_jobs(jobs, voice, parallel=3, retries=5)` starts workers 1,2,3 first; when one finishes, 4th starts, etc., all 20 done, `progress: 20/20`, order reading-order `ch40 p1..20` before `ch41` (verified via `asyncio.Queue` + `task_done`/`join`) | No error |
| Edge 429/throttle retry | `edge_tts.Communicate.save` raises `Exception("429")` on attempts 1-2 | `tts_text_to_mp3` retries `5x` `wait min(20,2*attempt)` (2,4,6,8,10? Actually 2*1=2, 2*2=4 ...) logs `retry 1/4 dla part_001.mp3: 429` etc., on 3rd success writes file, no throw | If still fails after 5, raises `RuntimeError TTS failed after 5` |
| Exhaust retries error | always raises | after 5 attempts raise `RuntimeError` with `last_error` chained, workers cancel remaining via `task.cancel` | Propagates, caller prints `ERROR: generation failed` and keeps existing files |
| _parts skip on re-run | `_parts/040_C40_part001.mp3` exists before `run_part_jobs` | `exists` guard → log `worker {id}: skip Chapter 040 part 001/002 (XX KB)` not `start`, `completed` still increments, `progress` counts skip as complete, no `tts_text_to_mp3` call, no new TTS request; also `build_generation_plan` already skipped job at plan time (`if not exists(chapter_mp3) and not exists(part_path)`) so re-run `Queued 0 new jobs` when all `_parts` exist | No error |
| Single existing _parts skip vs whole chapter skip | `_parts/040_C40_part001.mp3` exists, `part002` missing | queue contains only `part002` (via plan guard), runtime skip not needed for `001`; if `040_C40.mp3` (chapter merged) exists at `build_generation_plan` time, `jobs` for that chapter empty | Correct subset |
| Parallel 2 vs 3 | `parallel=2` vs `3` | both work, `parallel` workers created `asyncio.create_task(worker(i+1)) for i in range(parallel)` ; `parallel=1` also valid (sequential) | `parallel<1` → caller `ValueError` at CLI layer (not in core), core assumes `>=1` |
| Retries param propagation | `retries=2` custom | `tts_text_to_mp3(...,retries=2)` retries 2, log `retry 1/1` then fail | retries<1 → CLI error, not core |
| Voice param | `voice="pl-PL-ZosiaNeural"` | `edge_tts.Communicate(text, voice)` receives passed voice, saved file uses that voice | Invalid voice → edge raises, retry logic applies then error |
| Empty jobs | `jobs=[]` | `run_part_jobs` prints `No TTS jobs ... Existing files will be reused.` and returns without creating workers | No error |
| Retry sleep capping | attempt 10 (if retries 10) `2*10=20` cap `min(20,20)=20` | sleep never >20s even with higher retries | N/A |

</intent-contract>

## Code Map

- `Speak-EPUB-1.0.0/speak.py:116` — **READ & DELEGATE (3.1 done)** — `tts_text_to_mp3(text,output_path,voice,retries=5):116` `for attempt in 1..retries` `edge_tts.Communicate(text,voice).save` + `wait = min(20,2*attempt)` + log `retry {attempt}/{retries-1} for {Path.name}: {e}` + `asyncio.sleep` ; `Speak-EPUB-1.0.0/speak.py:207 run_part_jobs(jobs,voice,parallel,retries)` `asyncio.Queue[Optional[PartJob]]` , `for job in jobs: put_nowait` , `for _ in range(parallel): put None` , `worker: skip if exists else tts_text_to_mp3` + `progress` lock ; `speak.py:84 sanitize_filename` , `speak.py:112 split_text_for_tts` , `speak.py:203 build_generation_plan` już delegowane do `core/tts` w 3.1
- `Speak-EPUB-1.0.0/core/tts.py:29` — **EXTEND** — dopisać `import asyncio`, `import edge_tts` lazy w funkcji aby nie psuć importu bez deps, `from pathlib import Path` dla logu, `async def tts_text_to_mp3(...):` + `async def run_part_jobs(...):` + ewentualnie `def _retry_sleep(attempt): return min(20,2*attempt)`; zachować `sanitize_filename`, `PartJob`, `ChapterPlan`, `split_text_for_tts`, `build_generation_plan` z 3.1 bez zmian; `__all__` extend
- `Speak-EPUB-1.0.0/core/ports.py` — **READ-ONLY** — AD-1 boundary, nie dotykać
- `Speak-EPUB-1.0.0/core/clean.py` `core/epub.py` `core/fetch.py` `core/filters.py` — **READ-ONLY** — AD-2/AD-8/AD-9 nie dotykać
- `Speak-EPUB-1.0.0/core/config.py` — **READ-ONLY** — `handle_rpc` dispatcher, nie dodać TTS RPC w 3.2 (przełożyć na 3.2? Ale spec 3.2 nie wymaga RPC, tylko CLI `speak.py convert`); jeśli RPC potrzebny dla Tauri, to via `buildEpub` już, TTS RPC dopiero 3.3/4.x
- `Speak-EPUB-1.0.0/requirements.txt` — **READ-ONLY** — `edge-tts==7.2.8` pinned, nie zmieniać
- `Speak-EPUB-1.0.0/tests/test_tts.py` — **EXTEND** — I/O matrix 3.1 już 23 testy; dopisać 5 nowych dla 3.2 (queue parallel, retry, skip)
- `Speak-EPUB-1.0.0/tests/test_tts_integration.py` — **READ-ONLY** — parity 3.1, nie ruszać
- `src/*` `src-tauri/*` — **OFF-LIMIT** — Tauri GUI nie dotykać w 3.2

## Tasks & Acceptance

**Execution:**
- [x] `Speak-EPUB-1.0.0/core/tts.py` — EXTEND ratyfikacja brownfield TTS execution: przenieść logikę `speak.py:116 tts_text_to_mp3` do `core/tts.py` jako `async def tts_text_to_mp3(text,output_path,voice,retries=5)` z `edge_tts.Communicate` lazy import wewnątrz funkcji ( `try: import edge_tts` ), pętlą `for attempt in 1..retries` `await communicate.save(output_path)` + `wait = min(20,2*attempt)` + `print(f"        retry {attempt}/{retries-1} for {Path(output_path).name}: {e}")` + `await asyncio.sleep(wait)` , `raise RuntimeError` po wyczerpaniu; oraz `async def run_part_jobs(jobs,voice,parallel,retries)` z `asyncio.Queue` global order jak `speak.py:207-264` (put jobs, sentinel None×parallel, worker skip `if os.path.exists(output_path)` else `await tts_text_to_mp3`, `completed_lock` progress, `queue.task_done`, `await queue.join()` + `gather`, cancel on exception); zachować `sanitize/split/PartJob/build_plan` z 3.1; dodać `__all__` entries; czysty import `asyncio, os, edge_tts` bez `adapters`
- [x] `Speak-EPUB-1.0.0/speak.py` — EXTEND delegacja TTS: `speak.py:116 tts_text_to_mp3` i `speak.py:207 run_part_jobs` zamienić na `from core.tts import tts_text_to_mp3 as _core_tts` + `run_part_jobs as _core_run:69`; `Speak-EPUB-1.0.0/speak.py:118` — `tts_text_to_mp3` now `return await _core_tts(...)`; `Speak-EPUB-1.0.0/speak.py:196` — `run_part_jobs` now `return await _core_run(...)`; sygnatury preserved, `list_voices`/`ffmpeg_available`/`finalize_chapter_audio`/`build_m4b`/`convert` unchanged; parallel `1..6` warning `>6:417` and `retries>=1:420` still in `main`. Synced `speak.py` (root) via copy.
- [x] `Speak-EPUB-1.0.0/tests/test_tts.py` — EXTEND 5 nowych testów 3.2 na `core.tts` bezpośrednio z mock `edge_tts.Communicate`: `test_tts_retry_success_after_429` (2 fails then success, assert `save` called 3, file written, log `retry 1/4` captured), `test_tts_exhaust_retries_raises` (always fail 5 → `RuntimeError`, sleeps `[2,4,6,8]`), `test_run_part_jobs_parallel_3_queue_order` (20 jobs mock tts, `parallel=3` completes 20, `mock_calls` order preserves reading-order via `asyncio` sequential queue? verify `completed==20` and `progress` and that workers started 1,2,3 first), `test_run_part_jobs_skip_existing_parts` (pre-create 1 file, mock tts should not be called for that job, `skip` log, `jobs` from plan guard already tested in 3.1 but runtime skip also), `test_run_part_jobs_empty_jobs` (`jobs=[]` → `No TTS jobs` and no worker creation), plus `test_retry_sleep_capped_at_20`
- [x] `Speak-EPUB-1.0.0/tests/test_tts_mocked_integration.py` — OPTIONAL NEW — jeśli potrzeba osobnego pliku, lub rozszerzyć `test_tts.py`, test `speak` delegation parity: `speak.tts_text_to_mp3 is core.tts.tts_text_to_mp3` lub wrapper forwarding, oraz `parallel` param propagation `1..6`
- [x] `src/*` — NO CHANGE w 3.2 — OFF-LIMIT

**Acceptance Criteria:**
- Given queue 20 partów gdy start z `parallel 3` then `1,2,3` startują first, po zakończeniu jednego startuje `4-ty`, itd., z szacunkiem dla Edge throttling (verified via `run_part_jobs` `asyncio.Queue` + `parallel` workers + `None` sentinel, `progress: N/total`)
- Given Edge `429`/throttle gdy `tts_text_to_mp3` woła `edge-tts 7.2.8` then retry `5x` `backoff min(20,2*attempt)` z logiem `retry 1/4 dla part_02.mp3`, po wyczerpaniu error; istniejące `_parts/*.mp3` skip na re-run (resume) — `exists` guard w `run_part_jobs` + `build_generation_plan` guard z 3.1

## Spec Change Log


## Review Triage Log

### 2026-08-28 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 4: (high 1, medium 2, low 1)
- defer: 5: (high 0, medium 2, low 3)
- reject: 23
- addressed_findings:
  - `[high]` `[patch]` `Failure propagation not verified — added test_run_part_jobs_propagates_tts_failure with parallel=1, asserts RuntimeError propagates and part003 not called, fixed queue hang via drain logic in core/tts.py`
  - `[medium]` `[patch]` `Concurrency and exact order not verified — added test_run_part_jobs_max_concurrency_and_exact_order asserting max_concurrent==3 and call_order==expected 20, exact reading-order`
  - `[medium]` `[patch]` `ModuleNotFoundError retried pointlessly and partial file left — added except ModuleNotFoundError passthrough and partial unlink cleanup in tts_text_to_mp3`
  - `[low]` `[patch]` `Queue hang on worker exception — fixed run_part_jobs gather/drain logic to avoid deadlock on early worker exit`

## Design Notes

Ratyfikacja 3.2 przed 3.3: `core/tts.py` staje się jedynym ownerem `PartJob` queue execution. `speak.py` `convert` dalej orkiestruje `extract_chapters → split → build_plan → run_part_jobs → finalize`. `edge_tts` lazy import wewnątrz `tts_text_to_mp3` aby `py_compile` i import bez zainstalowanej `edge_tts` nie failował (CI bez deps). `asyncio.Queue` sentinel `None × parallel` jak `speak.py:216` gwarantuje determinizm kolejki.

```python
# core/tts.py extension
async def tts_text_to_mp3(text, output_path, voice, retries=5):
    for attempt in range(1, retries+1):
        try:
            import edge_tts
            await edge_tts.Communicate(text, voice).save(output_path)
            return
        except Exception as e:
            if attempt < retries:
                await asyncio.sleep(min(20, 2*attempt))
                print(f"        retry {attempt}/{retries-1} for {Path(output_path).name}: {e}")
            else:
                raise RuntimeError(...)
async def run_part_jobs(jobs, voice, parallel, retries):
    queue = asyncio.Queue()
    for job in jobs: queue.put_nowait(job)
    for _ in range(parallel): queue.put_nowait(None)
    # workers...
```

## Verification

**Commands:**
- `Speak-EPUB-1.0.0/venv\Scripts\python.exe -m py_compile Speak-EPUB-1.0.0/core/tts.py` -- 0 exit
- `Speak-EPUB-1.0.0/venv\Scripts\python.exe -m py_compile Speak-EPUB-1.0.0/speak.py` -- 0 exit
- `Speak-EPUB-1.0.0/venv\Scripts\python.exe -m pytest Speak-EPUB-1.0.0/tests/test_tts.py -v` -- 33 passed (23×3.1 +10×3.2 including concurrency + failure propagation)
- `Speak-EPUB-1.0.0/venv\Scripts\python.exe -m pytest Speak-EPUB-1.0.0/tests/test_tts_integration.py -v` -- 6 passed
- `Speak-EPUB-1.0.0/venv\Scripts\python.exe -m pytest Speak-EPUB-1.0.0/tests/test_clean.py Speak-EPUB-1.0.0/tests/test_filters.py Speak-EPUB-1.0.0/tests/test_epub.py -v` -- 47 passed
- `Speak-EPUB-1.0.0/venv\Scripts\python.exe -m pytest Speak-EPUB-1.0.0/tests -v` -- 196 passed
- `npm run build` -- Vite 50 modules 248kB OK

## Auto Run Result

Status: done
Blocking condition: none

Summary: Ratyfikowano Edge TTS execution do Core — `core/tts.py` rozszerzony o `tts_text_to_mp3` (lazy edge_tts, 5 retries `min(20,2*attempt)`, log `retry 1/4`, ModuleNotFound passthrough, partial cleanup) oraz `run_part_jobs` (global `asyncio.Queue` + `None` sentinel×parallel, skip `exists`, progress lock, drain fix dla hang), `Speak-EPUB-1.0.0/speak.py` i `speak.py` delegują, dodano 10 testów 3.2 (`retry success 429`, `exhaust`, `parallel 3 order 20`, `skip`, `empty`, `capped 20`, `delegation`, `parallel 2 vs 3`, `max concurrency exact order`, `failure propagation`) + 23 z 3.1 =33, weryfikacja 196 pytest +57 vitest + build czysta.

Files changed:
- `Speak-EPUB-1.0.0/core/tts.py:192` — EXTEND async tts_text_to_mp3 + run_part_jobs (ratyfikacja speak.py:116/207, fix ModuleNotFound + partial unlink + queue drain)
- `Speak-EPUB-1.0.0/speak.py:66` — EXTEND delegacja `from core.tts import tts_text_to_mp3/run_part_jobs` wrappers
- `speak.py:60` — SYNC delegacja root copy
- `Speak-EPUB-1.0.0/tests/test_tts.py:451` — EXTEND 10 nowych testów 3.2 (retry, parallel, skip, concurrency, propagation)

Review findings breakdown: patch 4 applied (high 1, medium 2, low 1), defer 5 (medium 2, low 3), reject 23

Follow-up review recommendation: true (patched high 1 => true, score 3*2+1=7)

Verification performed:
- `py_compile core/tts.py` 0
- `py_compile speak.py` 0
- `pytest test_tts.py -v` 33 passed
- `pytest test_tts_integration` 6 passed
- `pytest test_clean/filters/epub` 47 passed
- `pytest Speak-EPUB-1.0.0/tests` 196 passed
- `npm test` 57 passed
- `npm run build` OK

Residual risks:
- No timeout on Communicate.save — worker can hang (defer medium)
- Backoff without jitter — thundering herd (defer low)
- Structured logging missing — print interleaving (defer low)
- Parallel validation only at CLI (defer medium)
- Duplicate root delegation via copy (defer medium)
