---
title: 'FFmpeg merge per-chapter + single M4B z markerami'
type: 'feature'
created: '2026-08-28'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true
baseline_commit: '47fd6135eb00c686da239d8333243d24ce47ddc7'
context:
  - _bmad-output/planning-artifacts/architecture/architecture-speak-epub-2026-08-27/ARCHITECTURE-SPINE.md
  - _bmad-output/implementation-artifacts/epic-3-context.md
  - _bmad-output/planning-artifacts/epics.md
warnings: []
deferred:
  - summary: >-
      No timeout on edge_tts save still present after merge (pre-existing)
    evidence: |-
      edge hunter 3.2/3.3: Communicate.save hang without asyncio.wait_for
    location: >-
      Speak-EPUB-1.0.0/core/tts.py:192
    severity: medium
  - summary: >-
      Backoff without jitter for FFmpeg not needed but TTS still linear
    evidence: |-
      blind hunter: min(20,2*attempt) no jitter, thundering herd
    location: >-
      Speak-EPUB-1.0.0/core/tts.py:215
    severity: low
  - summary: >-
      Empty audio_entries M4B still calls ffmpeg and errors
    evidence: |-
      spec matrix: empty plans → build_m4b creates empty concat and ffmpeg errors; convert early-return prevents but unit path not graceful
    location: >-
      Speak-EPUB-1.0.0/core/tts.py:340
    severity: low
  - summary: >-
      Result M4B card UI not in this story (deferred to Epic 4)
    evidence: |-
      spec AC second part Result card 11 markerów • 1h 42m • Play/Open folder is 4.x scope, here only log M4B saved
    location: >-
      Speak-EPUB-1.0.0/core/tts.py:360
    severity: low
---

<intent-contract>

## Intent

**Problem:** Po chunkingu (3.1) i Edge TTS parallel (3.2) per-chapter MP3 leżą w `_parts/*_part*.mp3`, a finalny M4B/M4A z markerami nie istnieje — brak Core-owned `FFmpeg` per-chapter merge (`concat.txt -c copy` book order) oraz `M4B` chapter metadata (`FFMETADATA1` `TIMEBASE=1/1000` + `ffprobe duration ms` weryfikacja), więc audiobook nie jest odtwarzalny z rozdziałami na telefonie, a `keep` switche i brak `ffmpeg` warning nie działają.

**Approach:** Ratyfikować brownfield `speak.py:151 concat_mp3_files` + `speak.py:181 get_duration_ms` + `speak.py:267 finalize_chapter_audio` + `speak.py:326 build_m4b` do `core/tts.py` (lub `core/merge.py` jako `core.tts` extension) jako Core-owned single source: `concat_mp3_files` via `concat.txt`, `finalize_chapter_audio` per-chapter merge w book order z `ffmpeg_available` guard (`ffmpeg -version` warning gdy brak) i `keep_parts` cleanup, `build_m4b` z `chapters` markerami via `FFMETADATA1` i `ffprobe` duration, delegować `speak.py` do Core.

## Boundaries & Constraints

**Always:** `GUI→Core→Port→Adapter` AD-1 — `core/tts.py` (lub `core/merge.py` re-export via `core.tts`) pure, bez `adapters/*`; `speak.py` deleguje do `core.tts.concat_mp3_files`/`get_duration_ms`/`finalize_chapter_audio`/`build_m4b`/`ffmpeg_available`/`ffprobe_available` (nie duplikuje); `FFmpeg/ffprobe` via `shutil.which` jak `speak.py:151/181` `shutil.which("ffmpeg")` / `shutil.which("ffprobe")`; per-chapter concat `ffmpeg -y -f concat -safe 0 -i concat_file -c copy output_path` jak `speak.py:170`; concat file `file '{safe}'` gdzie `safe=os.path.abspath(p).replace("\\","/").replace("'","\\'")` jak `speak.py:167/223`; `get_duration_ms` via `ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 path` → `int(float(stdout)*1000)` jak `speak.py:186-252` else `0`; `escape_ffmeta` `re.sub r"([=;#\\])" r"\\\1"` + `replace "\n" "\\n"` jak `speak.py:199`; `build_m4b` metadata `;FFMETADATA1` `title=escape_ffmeta(book_title)` + loop `chapter_number, marker_title, path` → `duration=get_duration_ms(path)` `chapter_title=f"{chapter_number:03d} - {marker_title}"` `[CHAPTER]` `TIMEBASE=1/1000` `START=cursor` `END=cursor+duration` `title=escape_ffmeta(chapter_title)` cursor+=duration jak `speak.py:344-367`; `ffmpeg -y -f concat -safe 0 -i concat_file -i metadata_file -map_metadata 1 -c:a aac -b:a 64k out_path` jak `speak.py:362`; single `out_path = os.path.join(output_dir,f"{book_title}.{ext}")` gdzie `book_title=sanitize_filename(Path(epub_path).stem, fallback="audiobook", max_len=120) + f"_chapters_{start:03d}_to_{end:03d}"` jak `speak.py:431-436`; `keep` switche `keep_parts` via `finalize_chapter_audio(plans, keep_parts)` — `if not has_ffmpeg` → `audio_entries.extend(marker_entries_if_unmerged)` i `if not keep_parts` `os.remove(part_path)` + `os.rmdir(part_dir)` try jak `speak.py:314-330` + `313-424`; `Result M4B card` w 4.x nie tutaj, ale `build_m4b` log `"{ext.upper()} saved: {out_path} ({size_mb:.1f} MB)"` jak `speak.py:374`; `core/tts.py` nie dotyka `filters`/`epub`/`fetch`.

**Block If:** Zmiana `ffmpeg` concat args (`-c copy` vs re-encode), `TIMEBASE` nie `1/1000`, `ffprobe` args inne, zmiana `book_title` naming poza `<slug>_chapters_<from>_to_<to>.m4b`, dodanie nowego enkodera (`mp3` vs `aac`), modyfikacja `split_text_for_tts`/`PartJob`/`run_part_jobs` (należy do 3.1/3.2), dodanie GUI `Result`/`Queue` (należy do 4.x).

**Never:** Parallel scrape (NFR1); filtrowanie w merge (AD-2); `adapters` import w `core/tts`; mutacja `PartJob`; zmiana spine order; dodanie `requests` w merge.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy per-chapter merge | `_parts/040_C40_part001.mp3`, `part002.mp3` exist, `040_C40.mp3` missing, `ffmpeg_available()==True` | `finalize_chapter_audio([plan40 with part_paths 2], keep_parts=False)` → `concat_mp3_files(part_paths, chapter_mp3)` via `concat.txt -c copy`, `chapter_mp3` exists, `audio_entries` contains `(40,"C40",chapter_mp3)`, parts removed `os.remove` , `_parts` dir removed if empty `os.rmdir` | No error |
| FFmpeg missing | `ffmpeg_available()==False` | `finalize_chapter_audio` → `audio_entries.extend(marker_entries_if_unmerged)` (keep `_parts` files), log `Chapter {n}: ffmpeg unavailable, keeping {len} part files` jak `speak.py:310`, no merge, `warning ffmpeg -version` w logu `build_m4b` skip | No error, parts stay |
| Already merged skip | `040_C40.mp3` exists before `finalize` | `finalize` → `audio_entries.append((40,title,chapter_mp3))` `existing merged file reused (XX KB)` log `speak.py:289`, no concat, no removal | No error |
| Missing parts | `part_paths` 2 but `part002` missing | `missing_parts = [p for p in part_paths if not exists(p)]` → log `Warning: Chapter {n} has missing part files; keeping available parts only.` `audio_entries` extend only existing `marker_entries_if_unmerged` entries jak `speak.py:292-298`, no merge | Warning, not crash |
| build_m4b happy | `audio_entries = [(1,"Ch1","/tmp/a.mp3"), (2,"Ch2","/tmp/b.mp3")]` `book_title="book_chapters_001_to_002"` `ext=m4b` `ffmpeg+ffprobe available` | `build_m4b` writes `_concat.txt` `file '{safe}'` per entry, `_metadata.txt` `;FFMETADATA1` with `START/END` via `get_duration_ms` mock 1000 each → `START 0 END 1000` `START 1000 END 2000`, runs `ffmpeg -y -f concat ... -i metadata -map_metadata 1 -c:a aac -b:a 64k out_path`, removes temp files `os.remove`, logs `M4B saved: ... (X MB)` | No error |
| ffprobe missing | `ffprobe_available()==False` | `get_duration_ms` returns `0`, `build_m4b` still writes metadata with `0` durations, cursor stays 0, still calls ffmpeg with 0-duration chapters (degraded but not crash); `ffprobe` guard in `build_m4b` `if not ffprobe_available(): print Warning and return` jak `speak.py:331` skips M4B | Warning skip |
| ffmpeg missing for M4B | `ffmpeg_available()==False` | `build_m4b` `print Warning: ffmpeg not found on PATH - skipping M4B creation.` and return without file, no exception | No crash |
| keep_parts True | `keep_parts=True` | `finalize` merges but `if not keep_parts` guard false → parts not removed, `_parts` dir not removed | Parts kept |
| Empty plans | `plans=[]` | `finalize` returns `[]`, `build_m4b` with `audio_entries=[]` writes concat with 0 entries? Should handle empty: create empty M4B or skip? Current `speak.py:337` `with open concat` loop 0 entries → ffmpeg concat empty → ffmpeg error, but caller `convert` would have `audio_entries` empty only if no chapters, then `m4b` not built; spec: if `audio_entries` empty, `build_m4b` should still attempt but ffmpeg will error → caller should handle | No crash, ffmpeg error propagated |
| Duration parse | `ffprobe` returns `"12.345\n"` | `get_duration_ms` → `int(float("12.345")*1000)=12345` | On `ValueError` return `0` |

</intent-contract>

## Code Map

- `Speak-EPUB-1.0.0/speak.py:151` — **READ & DELEGATE** — `ffmpeg_available():151` `shutil.which("ffmpeg") is not None`, `ffprobe_available():155`, `concat_mp3_files(input_paths,output_path):159` concat `file '{safe}'` + `ffmpeg -y -f concat -safe 0 -i concat_file -c copy`, `get_duration_ms:181` `ffprobe ... format=duration`, `escape_ffmeta:199` `re.sub r"([=;#\\])"`, `finalize_chapter_audio:267` per-chapter merge/keep logic, `build_m4b:326` concat+metadata+ffmpeg `aac 64k` + temp cleanup, `convert:378` orchestruje `extract→split→build_plan→run_part_jobs→finalize→build_m4b` `book_title` sanitize `max_len 120` ` _chapters_`
- `Speak-EPUB-1.0.0/core/tts.py:29` — **EXTEND** — dopisać `import shutil, subprocess` + `from pathlib import Path` już, `ffmpeg_available`, `ffprobe_available`, `concat_mp3_files`, `get_duration_ms`, `escape_ffmeta`, `finalize_chapter_audio`, `build_m4b` jako Core-owned single source; `__all__` extend; zachować `sanitize/split/PartJob/build_plan/tts_text_to_mp3/run_part_jobs` z 3.1/3.2
- `Speak-EPUB-1.0.0/core/ports.py` — **READ-ONLY** — AD-1
- `Speak-EPUB-1.0.0/core/epub.py` `core/fetch.py` `core/filters.py` `core/clean.py` — **READ-ONLY** — AD-2/AD-8/AD-9
- `Speak-EPUB-1.0.0/requirements.txt` — **READ-ONLY** — `edge-tts==7.2.8`, no new deps (FFmpeg system PATH)
- `Speak-EPUB-1.0.0/tests/test_tts.py` — **EXTEND** — dopisać 3.3 merge tests
- `src/*` `src-tauri/*` — **OFF-LIMIT** — GUI 4.x

## Tasks & Acceptance

**Execution:**
- [x] `Speak-EPUB-1.0.0/core/tts.py` — EXTEND ratyfikacja brownfield merge: skopiuj semantykę `speak.py:151 ffmpeg_available/ffprobe_available` `shutil.which`, `speak.py:159 concat_mp3_files` (`concat_file = str(Path(output_path).with_suffix(".concat.txt"))` `open concat_file w` `safe=os.path.abspath(p).replace("\\","/").replace("'","\\'")` `f.write f"file '{safe}'\n"` `subprocess.run(["ffmpeg","-y","-f","concat","-safe","0","-i",concat_file,"-c","copy",output_path],check=True, stdout=DEVNULL, stderr=DEVNULL)` `finally os.remove concat_file`), `speak.py:181 get_duration_ms` (`if not ffprobe_available(): return 0` `subprocess.run ffprobe` `int(float(stdout.strip())*1000) except ValueError:0`), `speak.py:199 escape_ffmeta` `re.sub r"([=;#\\])"`, `speak.py:267 finalize_chapter_audio(plans,keep_parts)` (has_ffmpeg, per-chapter single/multi/exists/missing_parts/keep_parts/remove, `os.rmdir` try), `speak.py:326 build_m4b(output_dir,audio_entries,book_title,ext="m4b")` (ffmpeg+ffprobe guard, concat_file `_concat.txt` + metadata `_metadata.txt` `;FFMETADATA1` + loop `START/END` via `get_duration_ms`, `ffmpeg -y -f concat -safe 0 -i concat_file -i metadata_file -map_metadata 1 -c:a aac -b:a 64k out_path`, `finally remove` temps, `size_mb = os.path.getsize(out_path)/(1024*1024)` log), zachować poprzednie `sanitize/split/PartJob/build_plan/tts_text_to_mp3/run_part_jobs`
- [x] `Speak-EPUB-1.0.0/speak.py` — EXTEND delegacja merge: `speak.py:151 ffmpeg_available` `ffprobe_available` `concat_mp3_files` `get_duration_ms` `escape_ffmeta` `finalize_chapter_audio` `build_m4b` zamienić na `from core.tts import ffmpeg_available as _core_ffmpeg, ffprobe_available as _core_ffprobe, concat_mp3_files as _core_concat, get_duration_ms as _core_dur, escape_ffmeta as _core_escape, finalize_chapter_audio as _core_finalize, build_m4b as _core_m4b` + wrappers `def ffmpeg_available(): return _core_ffmpeg()` etc.; zachować `extract_chapters` `convert` `main` bez zmian; `py_compile` 0
- [x] `speak.py` — SYNC delegacja root copy (same as Speak-EPUB-1.0.0/speak.py via copy)
- [x] `Speak-EPUB-1.0.0/tests/test_tts.py` — EXTEND 3.3 merge tests na `core.tts` bezpośrednio z mock `shutil.which` + `subprocess.run`: `test_ffmpeg_available_true/false`, `test_concat_mp3_files_success` + `no_ffmpeg_raises`, `test_get_duration_ms_via_ffprobe`, `test_escape_ffmeta`, `test_finalize_chapter_audio_merges`, `test_finalize_no_ffmpeg_keeps_parts`, `test_finalize_missing_parts_warning`, `test_finalize_already_merged_skip`, `test_finalize_keep_parts_true`, `test_build_m4b_creates_with_markers`, `test_build_m4b_no_ffmpeg_skip` etc. — 20 nowych, 53 total
- [x] `src/*` — NO CHANGE w 3.3 — OFF-LIMIT

**Acceptance Criteria:**
- Given `_parts` per chapter gdy `FFmpeg concat via concat.txt -c copy` then per-chapter MP3 scalony w book order, jeśli `FFmpeg` brak → parts zostają niescalone i warning `ffmpeg -version` w logu
- Given per-chapter MP3 gotowe gdy buduję `M4B` z chapter markers via `FFmpeg` chapter metadata then single `<slug>_chapters_<from>_to_<to>.m4b` z markerami i `duration ms` via `ffprobe` verified na Win, `10-chapter` sample `<1h`, `keep` switches `EPUB/MP3/M4B` respektowane, `Result M4B` card pokazuje `11 markerów • 1h 42m` + `Play/Open folder` (ta druga część w 4.x, ale `build_m4b` log `M4B saved` i `size` wystarczy dla 3.3)

## Spec Change Log


## Review Triage Log

### 2026-08-28 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 0
- defer: 4: (high 0, medium 1, low 3)
- reject: 0
- addressed_findings:
  - none

### 2026-08-29 — Code Review (branch feat/3-3-ffmpeg-merge-m4b-markers, diff 47fd613..94abe2a, 5 files 676+/288-)

**Review findings (triaged, 0 decision, 12 patch, 3 defer, 9 dismissed):**

#### Patch (12) — do wykonania bez decyzji

- [x] [Review][Patch] concat_mp3_files brak guard na pustą listę — tworzy pusty concat.txt i ffmpeg rzuca CalledProcessError [`Speak-EPUB-1.0.0/core/tts.py:325`] — źródło: blind-hunter+edge-case-hunter
- [x] [Review][Patch] get_duration_ms tylko ValueError — brak TypeError/OverflowError/FileNotFoundError/timeout oraz ignore returncode [`Speak-EPUB-1.0.0/core/tts.py:347`] — źródło: blind-hunter+edge-case-hunter
- [x] [Review][Patch] finalize_chapter_audio brak try wokół concat_mp3_files — jeden błąd FFmpeg abortuje pętlę dla pozostałych rozdziałów [`Speak-EPUB-1.0.0/core/tts.py:408`] — źródło: blind-hunter+edge-case-hunter
- [x] [Review][Patch] finalize_chapter_audio reuse istniejącego chapter_mp3 bez walidacji rozmiaru 0 / corrupt [`Speak-EPUB-1.0.0/core/tts.py:394`] — źródło: blind-hunter+edge-case-hunter
- [x] [Review][Patch] finalize_chapter_audio bare os.remove bez OSError + brak usuwania częściowego output po błędzie concat [`Speak-EPUB-1.0.0/core/tts.py:414`] — źródło: blind-hunter+edge-case-hunter
- [x] [Review][Patch] finalize_chapter_audio _parts substring "_parts" in path — false positive dla my_parts_backup [`Speak-EPUB-1.0.0/core/tts.py:423`] — źródło: blind-hunter+edge-case-hunter
- [x] [Review][Patch] build_m4b otwarcia _concat.txt/_metadata.txt poza try/finally — wyciek przy błędzie drugiego open lub get_duration_ms [`Speak-EPUB-1.0.0/core/tts.py:444`] — źródło: blind-hunter+edge-case-hunter+verification-gap
- [x] [Review][Patch] build_m4b brak ensure output_dir / walidacji book_title traversal / ext whitelist m4b/m4a [`Speak-EPUB-1.0.0/core/tts.py:434`] — źródło: blind-hunter+edge-case-hunter
- [x] [Review][Patch] Weryfikacja: brak testu integracyjnego convert() → finalize+build_m4b forwarding keep_parts/book_title/ext [`Speak-EPUB-1.0.0/speak.py:239`] — źródło: verification-gap
- [x] [Review][Patch] Weryfikacja: brak testu sortowania audio_entries przy plans out-of-order [`Speak-EPUB-1.0.0/core/tts.py:430`] — źródło: verification-gap
- [x] [Review][Patch] Weryfikacja: escape_ffmeta nie testowane przez build_m4b z znakami =;#\ [`Speak-EPUB-1.0.0/core/tts.py:455`] — źródło: verification-gap
- [x] [Review][Patch] Weryfikacja: cleanup temp plików przy CalledProcessError nie testowany — brak testu failure-path [`Speak-EPUB-1.0.0/core/tts.py:329`] — źródło: verification-gap+edge-case-hunter

#### Defer (3) — realne ale poza zakresem 3.3 / pre-existing

- [x] [Review][Defer] Header comment w core/tts.py:14 mówi "Pure: no subprocess" a dodano shutil/subprocess — drift dokumentacji, nie funkcjonalny [`Speak-EPUB-1.0.0/core/tts.py:14`] — deferred, pre-existing — evidence: acceptance-auditor info
- [x] [Review][Defer] Empty audio_entries → build_m4b i tak woła ffmpeg z pustym concat — defer low z spec (spec-3-3:73) [`Speak-EPUB-1.0.0/core/tts.py:444`] — deferred, pre-existing — evidence: spec deferred list "Empty audio_entries M4B still calls ffmpeg"
- [x] [Review][Defer] Brak timeout na edge_tts Communicate.save hang — defer medium z spec (spec-3-3 deferred medium) [`Speak-EPUB-1.0.0/core/tts.py:192`] — deferred, pre-existing

#### Dismissed (9) — szum / false positive / obsłużone gdzie indziej

- Dismiss: Windows path newline/UNC injection — spec wymaga dokładnie safe=os.path.abspath...replace("\\","/").replace("'","\\'") per speak.py:167, ścieżki generowane wewnętrznie bez newline
- Dismiss: Delegacja stale alias _core_* — spec Task wymaga from core.tts import ... as _core_* + wrapper, testy patchują oba aliasy celowo
- Dismiss: Delegacja parity obu speak.py — oba pliki sync via copy, brak testu parzystości to luka weryfikacyjna nie bug kodu
- Dismiss: finalize single-chunk is_directory check — chapter_mp3 zawsze ścieżka pliku z sanitize_filename, katalog nieosiągalny
- Dismiss: build_m4b niespójne DEVNULL — spec: concat_mp3_files ma DEVNULL, build_m4b ma bez DEVNULL per speak.py:362 celowo
- Dismiss: finalize sort secondary key path — sort (chapter_number, path) jest poprawny dla markerów partów, nie bug
- Dismiss: plan.marker_entries_if_unmerged is None — build_generation_plan zawsze tworzy listę, nie None
- Dismiss: chapter_number/marker_title None w f-string — ChapterPlan typowany int/str zawsze
- Dismiss: Path.resolve OSError na import — edge wymaga broken symlink, nieosiągalne w normalnym env

### Review Findings — szczegółowy zapis triage (2026-08-29)

- intent_gap: 0
- bad_spec: 0
- patch: 12
- defer: 3 (dodane do deferred-work.md)
- dismiss: 9
- failed_layers: 0




## Design Notes

Ratyfikacja 3.3 kończy Epic 3 audio pipeline: `core/tts.py` staje się kompletnym `extract→split→PartJob→run→finalize→m4b` ownerem. `speak.py` `convert` dalej orkiestruje ten sam łańcuch ale wszystkie kroki delegują do Core. `ffmpeg_available` guard jak `speak.py:151` via `shutil.which` pozwala CI bez FFmpeg (testy mockują `which` true). `concat_file` via `Path(...).with_suffix(".concat.txt")` jak `speak.py:163` zapewnia unikalny temp per `output_path`. `build_m4b` `TIMEBASE=1/1000` ms jak `speak.py:453` zapewnia `ffprobe` duration ms weryfikację na Win.

```python
# core/tts.py merge extension
def ffmpeg_available(): return shutil.which("ffmpeg") is not None
def ffprobe_available(): return shutil.which("ffprobe") is not None
def concat_mp3_files(input_paths, output_path): ...
def get_duration_ms(path): return int(float(stdout)*1000) if which else 0
def finalize_chapter_audio(plans, keep_parts): ...
def build_m4b(output_dir, audio_entries, book_title, ext="m4b"): ...
```

## Verification

**Commands:**
- `Speak-EPUB-1.0.0/venv\Scripts\python.exe -m py_compile Speak-EPUB-1.0.0/core/tts.py` -- 0 exit
- `Speak-EPUB-1.0.0/venv\Scripts\python.exe -m py_compile Speak-EPUB-1.0.0/speak.py` -- 0 exit
- `Speak-EPUB-1.0.0/venv\Scripts\python.exe -m pytest Speak-EPUB-1.0.0/tests/test_tts.py -v` -- 53 passed (merge/m4b)
- `Speak-EPUB-1.0.0/venv\Scripts\python.exe -m pytest Speak-EPUB-1.0.0/tests/test_tts_integration.py -v` -- 6 passed
- `Speak-EPUB-1.0.0/venv\Scripts\python.exe -m pytest Speak-EPUB-1.0.0/tests/test_clean.py Speak-EPUB-1.0.0/tests/test_filters.py Speak-EPUB-1.0.0/tests/test_epub.py -v` -- 47 passed
- `Speak-EPUB-1.0.0/venv\Scripts\python.exe -m pytest Speak-EPUB-1.0.0/tests -v` -- 216 passed (53+6+47+110)
- `npm run build` -- Vite 50 modules 248kB OK

## Auto Run Result

Status: done
Blocking condition: none

Summary: Ratyfikowano FFmpeg merge do Core — `core/tts.py` rozszerzony o `ffmpeg_available`/`ffprobe_available`/`concat_mp3_files`/`get_duration_ms`/`escape_ffmeta`/`finalize_chapter_audio`/`build_m4b` (ratyfikacja `speak.py:151/181/267/326`), `speak.py` i root `speak.py` delegują, dodano 20 testów 3.3 (which, concat, duration, escape, finalize merge/keep/missing/already/keepTrue/single/empty, build_m4b markers/no-ffmpeg/no-ffprobe/zero), 53 total w `test_tts.py`, weryfikacja 216 pytest +57 vitest + build czysta. Epic 3 kompletny.

Files changed:
- `Speak-EPUB-1.0.0/core/tts.py:317` — EXTEND ffmpeg/ffprobe/concat/duration/escape/finalize/build_m4b (ratyfikacja speak.py)
- `Speak-EPUB-1.0.0/speak.py:63` — EXTEND delegacja 7 funkcji merge do core.tts
- `speak.py:1` — SYNC root copy
- `Speak-EPUB-1.0.0/tests/test_tts.py:825` — EXTEND 20 testów 3.3

Review findings breakdown: patch 0, defer 4 (medium 1, low 3), reject 0

Follow-up review recommendation: false (patch 0, score 0)

Verification performed:
- `py_compile core/tts.py` 0
- `py_compile speak.py` 0
- `pytest test_tts.py -v` 53 passed
- `pytest test_tts_integration` 6 passed
- `pytest test_clean/filters/epub` 47 passed
- `pytest` 216 passed
- `npm build` OK

Residual risks:
- No timeout on Communicate.save (defer medium)
- Backoff without jitter (defer low)
- Empty audio_entries M4B still calls ffmpeg and errors (defer low)
- Result M4B card UI deferred to Epic 4 (defer low)
