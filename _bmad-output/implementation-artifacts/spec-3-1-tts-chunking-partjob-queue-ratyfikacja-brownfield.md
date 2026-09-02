---
title: 'TTS Chunking + PartJob queue (ratyfikacja brownfield)'
type: 'feature'
created: '2026-08-28'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true
baseline_commit: 'f8d7d241ee4c5debd82eb15d51a29794a4bd604a'
context:
  - _bmad-output/planning-artifacts/architecture/architecture-speak-epub-2026-08-27/ARCHITECTURE-SPINE.md
  - _bmad-output/implementation-artifacts/epic-3-context.md
  - _bmad-output/planning-artifacts/epics.md
warnings: []
deferred:
  - summary: >-
      Windows reserved names (CON/PRN/AUX/NUL/COM1 etc) not handled in sanitize_filename
    evidence: |-
      blind hunter found sanitize_filename only replaces [\\/:*?"<>|] and collapses whitespace, not reserved names or trailing dot/space; Speak-EPUB-1.0.0/speak.py:84 mirror retains this gap
    location: >-
      Speak-EPUB-1.0.0/core/tts.py:29
    severity: low
  - summary: >-
      Sanitized title collision after truncation to 60 chars can overwrite distinct chapters
    evidence: |-
      blind hunter: different titles like a/b and a_b or truncation to 60 maps to same f"{number:03d}_{safe}.mp3"; build_generation_plan does not dedupe seen paths
    location: >-
      Speak-EPUB-1.0.0/core/tts.py:138
    severity: medium
  - summary: >-
      TOCTOU between exists check and job use not guarded for parallel resume
    evidence: |-
      edge-case hunter: if not os.path.exists(chapter_mp3) and not os.path.exists(part_path) does not guard concurrent creation when --parallel 2-3 resumes
    location: >-
      Speak-EPUB-1.0.0/core/tts.py:173
    severity: medium
  - summary: >-
      Workspace root speak.py duplicate still defines PartJob/sanitize/split/build locally, drifts from Speak-EPUB-1.0.0/speak.py delegation
    evidence: |-
      verification-gap other finding: staged change updates only Speak-EPUB-1.0.0/speak.py; root speak.py:65 retains own PartJob/ChapterPlan/sanitize_filename/split_text_for_tts/build_generation_plan with stray return_marker = None
    location: >-
      speak.py:65
    severity: medium
  - summary: >-
      Sanitize fallback divergence between core/epub.py (/// -> fallback) and core/tts.py (/// -> "___") undocumented
    evidence: |-
      verification-gap other: core/epub.py strips _. vs core/tts.py preserves "___"; both asserted in tests but divergence not documented as intentional brownfield keep
    location: >-
      Speak-EPUB-1.0.0/core/tts.py:29
    severity: low
---

<intent-contract>

## Intent

**Problem:** Istniejący `Speak-EPUB-1.0.0/speak.py` ma działające `split_text_for_tts` 3500 + `PartJob` frozen + `build_generation_plan` w globalnej kolejce reading-order, ale duplikacja poza `core/` łamie AD-1/AD-8 i blokuje deterministyczną kolejkę PartJob dla audiobooka M4B — brak single source of truth dla TTS chunku i queue, a re-run skip `_parts/*.mp3` nie jest w Core.

**Approach:** Zratyfikować brownfield do `core/tts.py` jako Core-owned single source: przenieść `split_text_for_tts` (sentence-boundary 3500 + hard-cut fallback >3500), `PartJob` frozen (`chapter_number, part_number, part_count, text, output_path, is_final_chapter_file` + `chapter_title` zachowane dla compat) oraz `build_generation_plan` (global queue reading-order `ch40 p1..20` przed `ch41 p1`), delegować `speak.py` do `core.tts`, bez zmiany semantyki ani dodawania filtrów przed EPUB gate.

## Boundaries & Constraints

**Always:** `GUI→Core→Port→Adapter` AD-1 — `core/tts.py` pure, bez importów `adapters/*` ani `speak.py` logiki fetch/clean; `speak.py` deleguje do `core.tts.split_text_for_tts`/`build_generation_plan`/`PartJob` (nie duplikuje); cache key `sha1(normalized_url)` AD-9 + `raw` never filtered AD-2 + EPUB jako invariant AD-8 (TTS czyta только EPUB via `extract_chapters`); chunk max 3500 na granicy zdań `(?<=[.!?;:])\s+` jak `speak.py:135`; sentence >3500 → hard cut `sentence[start:start+max_chars]` jak `speak.py:150-157`; wszystkie chunki `<=3500` i w kolejności `chunks.append` kolejno; PartJob frozen dataclass `frozen=True` z polami `chapter_number, part_number, part_count, text, output_path, is_final_chapter_file` + `chapter_title` opcjonalnie zachowane dla `speak.py` compat (test sprawdza frozen i obecność 6 wymaganych pól); global queue reading-order: `for chapter in chapters: for part in chunks: queue.append(PartJob)` — `ch40 p1..20` w całości przed `ch41 p1`; output paths `Speak-EPUB-1.0.0/speak.py:295` format `f"{chapter_number:03d}_{safe}_part{part_number:03d}.mp3"` w `_parts` oraz single-chunk `"{chapter_number:03d}_{safe}.mp3"` gdy `is_final_chapter_file=True`; sanitize via `re.sub r'[\\/:*?"<>|]'` + `speak.py:84 sanitize_filename`; whitespace collapse `re.sub r"\s+"`; single chunk case `len(chunks)==1` → `chapter_mp3` bezpośrednio, nie `_parts`; empty text `len<=100` skip jak `extract_chapters:117` — ten spec nie zmienia `extract_chapters`; `store.json` `chunk-size` mirror AD-10 nie modyfikowany tutaj.

**Block If:** Zmiana semantyki chunkingu (inny `max_chars` default poza 3500, inny separator zdań, `max_chars` <500 lub >10000 bez CLAMP), zmiana `PartJob` pól poza `frozen` + 6 wymaganych (np. usunięcie `is_final_chapter_file` lub `text`), dodanie równoległości fetch tutaj (NFR1 `no parallel scrape`), aplikowanie filtrów w `core/tts.py` (AD-2 zakaz), zmiana naming `<slug>_chapters_<from>_to_<to>.m4b` (należy do 3.3), dodanie `edge-tts` wywołania poza `tts_text_to_mp3` (należy do 3.2), zmiana `extract_chapters` spine order 1..N.

**Never:** Parallel scrape (NFR1) w chunkerze; filtrowanie `raw`/`cleaned` w `tts.py` (AD-2 — filtry tylko w `epub.py` gate); duplikacja `split_text_for_tts` poza `core/tts.py` (DRY violation); `adapters/*` import w `core/tts.py`; mutacja `PartJob` po utworzeniu (frozen); dodanie nowej zależności `Edge TTS` lub `FFmpeg` tutaj (należy do 3.2/3.3); zmiana `chapter_number` poza spine order; dodanie UI/Result card (3.3/4.x).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy single >3500 | `text = "Sentence one. " * 800` (~5600 chars) | `split_text_for_tts(text,3500)` returns 2 chunks `len<=3500`, split at sentence boundary `(?<=[.!?;:])\s+`, `chunks[0].endswith("." )` and `chunks[1].startswith("Sentence")`, order preserved | No error |
| Hard cut | single sentence ` "a"*4000` (no `.!?;:`) | single sentence >3500 fallback hard cut → `["a"*3500, "a"*500]`, `len==2`, `all len<=3500` | No error |
| Exact boundary mixed | `text = "Foo! Bar? Baz; qux. "` repeated to 3501 | chunks split so `current + sentence` overflow → `flush_current`, no chunk >3500, no lost sentence | No error |
| Empty/whitespace | `text = "   "` | `[]` | No error, not `[""]` |
| Single chunk | `text = "Hello world"` + `chapter_number=5` single-chunk plan | `build_generation_plan([ (5,"T","Hello world")], out, 3500)` → `plans[0].chapter_mp3 == f"005_T.mp3"`, `jobs=[PartJob(5,1,1,"Hello world", chapter_mp3, is_final=True)]` | Not in `_parts` |
| Multi chunk plan | `chapters = [(40,"C40","x"*7001), (41,"C41","y"*2000), (42,"C42","z"*7001)]` where `7001` → 3 chunks 3500+3500+1? Actually split via sentences: assume hard cuts 3500,3500,1 | `build_generation_plan` → `jobs` length `2+1+2=5?` Depends on sentence split, but **global queue order** `jobs[0].chapter_number=40 part1`, `jobs[1]=40 part2`, `jobs[2]=41 part1`, `jobs[3]=42 part1`, `jobs[4]=42 part2`; all `is_final_chapter_file==False` for multi-part, `part_paths` under `_parts` | Not error |
| Frozen immutability | `job = PartJob(...)` | `job.text = "x"` raises `FrozenInstanceError`/`dataclasses.FrozenInstanceError` | Mutation forbidden |
| Whitespace collapse | `text = "Foo  \n  bar\t baz"` | collapsed `"Foo bar baz"` single chunk | No error |
| Semicolon/colon boundary | `text = "a; b: c. d!"` 3500 limit large | split at `;` and `:` boundaries counted as sentence ends, chunks preserve `";"` `":"` | No error |
| Output path sanitize | title `"A/B:C?D*"` | `safe_title = sanitize_filename("A/B:C?D*")` → `"A_B_C_D_"` used in `003_A_B_C_D_.mp3` and part files | fallback `Chapter_003` if after sanitize empty |
| Existing file skip planning | `jobs` contains `output_path` that exists on disk | `build_generation_plan` still creates Job if `chapter_mp3` not exists but `part_path` exists? Spec: `if not os.path.exists(chapter_mp3) and not os.path.exists(part_path): jobs.append` — so existing part skipped at plan time (resume hint for 3.2) | No duplicate job |

</intent-contract>

## Code Map

- `Speak-EPUB-1.0.0/speak.py:64` — **READ & DELEGATE** — `PartJob` frozen `chapter_number, chapter_title, part_number, part_count, text, output_path, is_final_chapter_file` `@dataclass(frozen=True)` + `split_text_for_tts(text,max_chars=3500):128` sentence `re.split r"(?<=[.!?;:])\s+"` + fallback hard cut `sentence[start:start+max_chars]` + whitespace `re.sub r"\s+"` + `build_generation_plan(chapters,output_dir,chunk_size):259` global queue reading-order `ch40 p1..20` before `ch41` + `sanitize_filename:84` + `extract_chapters:91` spine order + `tts_text_to_mp3:172` (off-limit until 3.2) + `finalize_chapter_audio/build_m4b` (off-limit 3.3)
- `Speak-EPUB-1.0.0/core/tts.py` — **NEW** — `split_text_for_tts(text,max_chars=3500)->list[str]` + `PartJob` frozen + `sanitize_filename` mirror `speak.py:84` + `ChapterPlan` dataclass (optional) + `build_generation_plan(chapters,output_dir,chunk_size)->(plans,jobs)` pure, bez `edge_tts`/`subprocess`, tylko `os.path`/`Path`/`re`, własne `sanitize` nie importuje `speak.py`
- `Speak-EPUB-1.0.0/core/ports.py:13` — **READ-ONLY** — `Selectors/ChapterInfo/ChapterContent/SearchResult` DTOs, AD-1 boundary
- `Speak-EPUB-1.0.0/core/clean.py` — **READ-ONLY** — selector isolation, nie dotykać (AD-7)
- `Speak-EPUB-1.0.0/core/epub.py:1` — **READ-ONLY** — EPUB assembly gate AD-8, future `extract_chapters` czyta EPUB jako TTS źródło; ten spec nie modyfikuje
- `Speak-EPUB-1.0.0/core/fetch.py:56` — **READ-ONLY** — `cache_key/read_cache` sha1 AD-9, nie dotykać
- `Speak-EPUB-1.0.0/core/filters.py` — **READ-ONLY** — AD-2 zakaz filtrowania w tts
- `Speak-EPUB-1.0.0/core/config.py:41` — **READ-ONLY** — `DEFAULT_STORE chunk-size 3500` AD-10, `handle_rpc` dispatcher; nie dodać `tts` RPC w 3.1 (przełożyć na 3.2)
- `src-tauri/src/lib.rs` — **OFF-LIMIT** — Rust sidecar `resolve_venv_python`, nie dotykać
- `Speak-EPUB-1.0.0/tests/test_epub.py` — **READ-ONLY** — pattern testów Core pure; naśladowana struktura dla nowych testów
- `Speak-EPUB-1.0.0/tests/test_clean.py` — **REFERENCE** — selector/heuristic test pattern

## Tasks & Acceptance

**Execution:**
- [x] `Speak-EPUB-1.0.0/core/tts.py` — NEW ratyfikacja brownfield: skopiuj semantykę `speak.py:84 sanitize_filename`, `speak.py:128 split_text_for_tts` (whitespace `re.sub r"\s+"`, `re.split r"(?<=[.!?;:])\s+"`, `current` flush, `len(sentence)>max_chars` hard cut `while start`, `len(current)+1+len(sentence)<=max_chars`), `speak.py:64 PartJob` `frozen=True` zachowując pola `chapter_number, chapter_title, part_number, part_count, text, output_path, is_final_chapter_file` (dodaj `chapter_title` dla compat, ale `__post_init__` nie mutuje; spec AC sprawdza 6 wymaganych pól + `chapter_title` optional), oraz `build_generation_plan` z `speak.py:259` (safe_title sanitize, `os.path.join(output_dir,"_parts")`, single-chunk `chapter_mp3` vs multi `_parts` parts, `if not os.path.exists(chapter_mp3) and not os.path.exists(part_path)` guard, `ChapterPlan` mirror `speak.py:75` jeśli potrzebne, global order preservation)
- [x] `Speak-EPUB-1.0.0/speak.py` — EXTEND delegacja: po utworzeniu `core/tts.py` zmień `speak.py:split_text_for_tts` i `PartJob`/`build_generation_plan`/`sanitize_filename` aby importowały z `core.tts` i delegowały (np. `from core.tts import PartJob, split_text_for_tts, build_generation_plan, sanitize_filename as _sanitize` i wrapper zachowujący sygnaturę), nie duplikuj logiki; zachowaj `if __name__ == "__main__": main()` oraz `tts_text_to_mp3`/`run_part_jobs`/`finalize_chapter_audio` bez zmian; zapewnij `python -m py_compile speak.py` 0 i backward import `from speak import split_text_for_tts` nadal działa
- [x] `Speak-EPUB-1.0.0/tests/test_tts.py` — NEW I/O matrix coverage: test happy single >3500 sentence-boundary `all len<=3500 and order preserved`, hard cut single sentence 4000→2 chunks `3500,500`, empty/whitespace `[]`, whitespace collapse, semicolon/colon boundary, single-chunk plan `is_final=True` path not in `_parts`, multi-chunk plan global order `40 p1..2 before 41`, output sanitize `"A/B:C?D*"` → `A_B_C_D_`, frozen immutability `pytest.raises(FrozenInstanceError)`, existing-file-skip guard via `tmp_path` `exists(part_path)` → job not queued; użyj `core.tts` bezpośrednio (nie `speak.py`) dla source-of-truth
- [x] `Speak-EPUB-1.0.0/tests/test_tts_integration.py` — OPTIONAL NEW (lub rozszerz `test_tts.py`) — porównawcza parzystość brownfield: dla 10 losowych `texts` (w tym `7001 chars`, whitespace, hard-cut) assert `core.tts.split_text_for_tts(text,3500) == speak.split_text_for_tts(text,3500)` oraz `core.tts.build_generation_plan(chapters, tmp,3500)[1]` == `speak.build_generation_plan(...) [1]` po normalizacji `output_path` (parzystość ratyfikacji)
- [x] `src/lib/sidecar.ts` + `src/hooks/*` — NO CHANGE w 3.1 — udokumentuj jako `OFF-LIMIT` w Code Map; nie dodawaj `callSidecar` dla TTS

**Acceptance Criteria:**
- Given rozdział `>3500` chars gdy `split_text_for_tts` (`core.tts` oraz delegowany `speak.split_text_for_tts`) dzieli then tnie na granicy zdań `(?<=[.!?;:])` z fallback twardym cięciem jeśli zdanie `>3500`, wszystkie chunki `≤3500` i w kolejności wejściowych zdań, bez utraty znaków poza collapsed whitespace
- Given EPUB z 3 rozdziałami `(40:"C40" 7001 chars →2 chunki, 41:"C41" 2000→1, 42:"C42" 7001→2)` gdy `build_generation_plan(chapters, output_dir, 3500)` buduje queue then `PartJob` frozen dataclass (`chapter_number, part_number, part_count, text, output_path, is_final_chapter_file` obecne, `frozen=True`, `chapter_title` zachowane dla compat) w globalnej kolejce reading order: `ch40 p1..2` najpierw, potem `ch41 p1`, potem `ch42 p1..2`, `part_paths` pod `_parts` dla multi-part, `chapter_mp3` single gdy 1 chunk, sanitize poprawny, `is_final_chapter_file` false dla `_parts` / true dla single

## Spec Change Log


## Review Triage Log

### 2026-08-28 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 4: (high 1, medium 2, low 1)
- defer: 5: (high 0, medium 3, low 2)
- reject: 27
- addressed_findings:
  - `[high]` `[patch]` `Verify _parts dir creation — added test_parts_dir_created_on_multi asserting (Path(out)/"_parts").is_dir() after fresh multi-chunk build, fixing missing FS side-effect verification`
  - `[medium]` `[patch]` `Verify single-chunk resume guard — added test_single_chunk_resume_skip creating 005_T.mp3 before build_generation_plan and asserting jobs == []`
  - `[medium]` `[patch]` `Fix parity baseline-only masking — extended test_tts_integration with test_parity_build_generation_plan_forwards_output_dir_and_chunk_size (2000 vs 3500, prefix checks) and test_sanitize_parity_with_max_len_120`
  - `[low]` `[patch]` `Remove unused Path import in core/tts.py — pure module now only os/re/dataclasses/typing`

## Design Notes

Ratyfikacja brownfield: `speak.py` jest referencją złotą, nie spec papierowy. `core/tts.py` kopiuje dokładnie `re.split` i `hard cut` pętlę oraz `build_generation_plan` guard `if not exists(chapter_mp3) and not exists(part_path)`. Delegacja w `speak.py` zachowuje `import speak` compat dla CLI `python speak.py --start-chapter 36 --m4b`. Frozen gwarantuje `hash` i `queue` determinizm przy `asyncio.Queue`. Global order wymuszony pętlą `for ch in chapters:` zewnętrzną, nie sortem `part_number`.

```python
# core/tts.py skeleton (golden shape)
@dataclass(frozen=True)
class PartJob:
    chapter_number: int
    chapter_title: str  # compat retained
    part_number: int
    part_count: int
    text: str
    output_path: str
    is_final_chapter_file: bool

def split_text_for_tts(text: str, max_chars: int = 3500) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    ...
    sentences = re.split(r"(?<=[.!?;:])\s+", text)
    ...
```

## Verification

**Commands:**
- `Speak-EPUB-1.0.0/venv\Scripts\python.exe -m py_compile Speak-EPUB-1.0.0/core/tts.py` -- 0 exit, no import `adapters`/`speak` cycle
- `Speak-EPUB-1.0.0/venv\Scripts\python.exe -m py_compile Speak-EPUB-1.0.0/speak.py` -- 0 exit, delegation intact
- `Speak-EPUB-1.0.0/venv\Scripts\python.exe -m pytest Speak-EPUB-1.0.0/tests/test_tts.py -v` -- 23 passed (happy/hard-cut/empty/semicolon/sanitize/frozen/order/skip/resume/_parts)
- `Speak-EPUB-1.0.0/venv\Scripts\python.exe -m pytest Speak-EPUB-1.0.0/tests/test_tts_integration.py -v` -- 6 passed (parity split + build + delegation prefix + max_len 120)
- `Speak-EPUB-1.0.0/venv\Scripts\python.exe -m pytest Speak-EPUB-1.0.0/tests/test_clean.py Speak-EPUB-1.0.0/tests/test_filters.py Speak-EPUB-1.0.0/tests/test_epub.py -v` -- 47 passed, no regression
- `Speak-EPUB-1.0.0/venv\Scripts\python.exe -m pytest Speak-EPUB-1.0.0/tests -v` -- 186 passed
- `npm test -- src/components/Result.test.tsx` -- 57 passed (8 files)
- `npm run build` -- Vite 50 modules 247kB gzip 75kB OK

**Manual checks (if no CLI):**
- `python -c "from core.tts import split_text_for_tts; assert split_text_for_tts('a'*4000)==['a'*3500,'a'*500]"`
- `python -c "from core.tts import PartJob; j=PartJob(1,'T',1,1,'hi','/tmp/x',True); j.text='x'"` raises FrozenInstanceError

## Auto Run Result

Status: done
Blocking condition: none

Summary: Zratyfikowano brownfield TTS do Core — `core/tts.py` jako single source `sanitize_filename`/`split_text_for_tts` 3500 sentence-boundary + hard-cut + `PartJob` frozen + `ChapterPlan` + `build_generation_plan` global reading-order z guardami `exists`, delegacja `Speak-EPUB-1.0.0/speak.py` bez duplikacji, dodano testy `test_tts.py:23` + `test_tts_integration.py:6` pokrywające I/O matrix i parzystość delegacji (`output_dir`/`chunk_size`/`max_len=120` oraz resume/_parts), import `Path` usunięty, weryfikacja 186 pytest + 57 vitest + Vite build czysta.

Files changed:
- `Speak-EPUB-1.0.0/core/tts.py:1` — NEW pure Core-owned chunking + PartJob + build_generation_plan (ratyfikacja speak.py:84/128/259)
- `Speak-EPUB-1.0.0/speak.py:60` — EXTEND delegacja `from core.tts import PartJob, ChapterPlan, sanitize_filename, split_text_for_tts, build_generation_plan`
- `Speak-EPUB-1.0.0/tests/test_tts.py:1` — NEW 23 testów I/O matrix + single-chunk resume + _parts dir
- `Speak-EPUB-1.0.0/tests/test_tts_integration.py:1` — NEW/EXTEND 6 testów parity brownfield + delegation prefix/max_len

Review findings breakdown: patch 4 applied (high 1, medium 2, low 1), defer 5 (medium 3, low 2), reject 27

Follow-up review recommendation: true (patched high 1 => true, score 3*2+1=7 >=5)

Verification performed:
- `py_compile core/tts.py` 0
- `py_compile speak.py` 0
- `pytest test_tts.py -v` 23 passed
- `pytest test_tts_integration.py -v` 6 passed
- `pytest test_clean/test_filters/test_epub` 47 passed
- `pytest Speak-EPUB-1.0.0/tests` 186 passed
- `npm test` 57 passed
- `npm run build` Vite OK 247kB

Residual risks:
- `sanitize_filename "___"` vs `core/epub.py "fallback"` divergence undocumented intentional keep (defer)
- `sanitize` collision after 60 truncation still overwrites distinct chapters (defer)
- `TOCTOU` exists check not atomic for parallel resume (defer medium)
- `speak.py` root duplicate drifts from `Speak-EPUB-1.0.0/speak.py` delegation (defer medium, not fixed to keep scope narrow)
- `chunk_size` 0/None validation missing — preserves speak.py TypeError semantics, not added (reject)
- `Path` import removed but typing `List` vs `list` inconsistency remains in other modules (low, reject)
