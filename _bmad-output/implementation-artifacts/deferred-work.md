- source_spec: `C:/Users/admin/Documents/programowanie/speak epub/_bmad-output/implementation-artifacts/spec-1-1-scaffold-tauri-python-sidecar-scraperport-tokeny.md`
  summary: Rust sidecar spawn does not drain stderr and does not kill child on 2s timeout, risking deadlock and zombie processes
  evidence: edge-case-hunter found src-tauri/src/lib.rs:110-115 stderr piped but never drained and 128-140 timeout does not kill child; verification-gap shows real spawn path is mocked for ping/hello so defect ships undetected

- source_spec: `C:/Users/admin/Documents/programowanie/speak epub/_bmad-output/implementation-artifacts/spec-1-1-scaffold-tauri-python-sidecar-scraperport-tokeny.md`
  summary: Rust venv path duplication lacks cross-verification test with Python core/config.py
  evidence: verification-gap reviewer traced get_venv_python vs resolve_venv_python parity — no Rust test asserts equality; inverting cfg branches would not fail scripts/verify.py

- source_spec: `C:/Users/admin/Documents/programowanie/speak epub/_bmad-output/implementation-artifacts/spec-1-1-scaffold-tauri-python-sidecar-scraperport-tokeny.md`
  summary: i18n locale toggle and store persistence not fully integrated (in-memory only, no tauri-plugin-store sync)
  evidence: blind hunter src/App.tsx:23 setLocale in-memory only; src/i18n/index.ts:33 t() no pluralization/missing-key warning; Epic 4 will own full Settings persist — scaffold deliberately minimal

- source_spec: `C:/Users/admin/Documents/programowanie/speak epub/_bmad-output/implementation-artifacts/spec-1-1-scaffold-tauri-python-sidecar-scraperport-tokeny.md`
  summary: Tauri CSP is null and frontend fetch lacks CSP isolation for http://localhost:17381 fallback
  evidence: blind hunter src-tauri/tauri.conf.json:26 security.csp null; not required for scaffold spike but should be hardened before networked fetch in Epic 2

- source_spec: C:/Users/admin/Documents/programowanie/speak epub/_bmad-output/implementation-artifacts/spec-1-2-adapter-novelphoenix-search-listchapters-cover-metadata.md
  summary: Pagination for listChapters beyond single page not handled � multi-page chapter listings truncated
  evidence: blind hunter found listChapters does single GET only (adapters/novelphoenix.py:149-194) with no next-page loop; site drift to paginated list would silently lose chapters without test coverage

- source_spec: C:/Users/admin/Documents/programowanie/speak epub/_bmad-output/implementation-artifacts/spec-1-2-adapter-novelphoenix-search-listchapters-cover-metadata.md
  summary: SearchResult author/cover fields not wired to EPUB cover pipeline and lack UI plumbing
  evidence: verification-gap traced author extraction (ports.py:32, novelphoenix.py:99-103) and cover_url (ports.py:33, novelphoenix.py:92,130) � tests never assert author, and _last_cover_url class attribute requires separate plumbing to core/epub.py not in this story

- source_spec: C:/Users/admin/Documents/programowanie/speak epub/_bmad-output/implementation-artifacts/spec-1-2-adapter-novelphoenix-search-listchapters-cover-metadata.md
  summary: fetchChapter 5xx/Timeout/429 retry and aggregator 5s non-blocking timeout lack tight verification
  evidence: verification-gap showed fetchChapter Timeout/ConnectionError/5xx/429 have no pinning test (only 404 tested at tests/test_novelphoenix.py:324 with weak code check) and aggregator timeout test allows 5-7s window so wait=False regression would not fail

- source_spec: C:/Users/admin/Documents/programowanie/speak epub/_bmad-output/implementation-artifacts/spec-1-2-adapter-novelphoenix-search-listchapters-cover-metadata.md
  summary: HTTP helper missing explicit UA/timeout assertion and imbalance of 4xx retry wastes politeness budget
  evidence: blind hunter noted retry policy marks any 4xx as retryable (adapters/_http.py:42-45) and no test asserts UA SpeakEPUB/1.0 or timeout 12; 404 would incur 2 jittered sleeps before [] or AdapterError

- source_spec: `C:/Users/admin/Documents/programowanie/speak epub/_bmad-output/implementation-artifacts/spec-1-3-powierzchnia-find-input-agregator-tabela-wyników.md`
  summary: handle_rpc search/listChaptersCount/guessAdapter serializacja i walidacja bez testów automatycznych — regresja nie zostanie złapana
  evidence: verification-gap: brak testów `handle_rpc` w `tests/*.py` ani `*.test.*`; `npm test` mockuje `callSidecar`, `pytest` testuje `NovelPhoenixAdapter` bezpośrednio — zmiana truncate/VALUE_ERROR/serializacji `link`/`chapters` przechodzi niezauważona

- source_spec: `C:/Users/admin/Documents/programowanie/speak epub/_bmad-output/implementation-artifacts/spec-1-3-powierzchnia-find-input-agregator-tabela-wyników.md`
  summary: useDebouncedSearch URL mode, empty, truncate 350→200, timeout 5s i normalizacja bez pinujących testów
  evidence: verification-gap: `FindInput.test.tsx` 5 testów tylko happy-title, brak URL/empty/timeout/error/normalizacji; zmiana `isUrlLike`/`truncateTitle`/`Promise.race` nie psuje testów

- source_spec: `C:/Users/admin/Documents/programowanie/speak epub/_bmad-output/implementation-artifacts/spec-1-3-powierzchnia-find-input-agregator-tabela-wyników.md`
  summary: FindInput clear/paste/searching spinner nietestowane — martwe affordance przeszłoby
  evidence: verification-gap: brak klików clear/paste ani mock `navigator.clipboard.readText` ani `role=status` spinner; usunięcie `handleClear`/`handlePaste` nie psuje `FindInput.test.tsx`

- source_spec: `C:/Users/admin/Documents/programowanie/speak epub/_bmad-output/implementation-artifacts/spec-1-3-powierzchnia-find-input-agregator-tabela-wyników.md`
  summary: ResultsTable Home/End/Space i fallback `—` dla `site`/`chapters` bez weryfikacji
  evidence: verification-gap: test keyboard tylko `ArrowDown`+`Enter`, brak `Home`/`End`/`Space`, brak render `site:""`→`—` i `results=[]`→hidden; usunięcie branchy nie psuje testów

- source_spec: `C:/Users/admin/Documents/programowanie/speak epub/_bmad-output/implementation-artifacts/spec-1-3-powierzchnia-find-input-agregator-tabela-wyników.md`
  summary: App Find skeleton/no-results CTA focus i error toast testowane przez Harness double zamiast real App — luka weryfikacyjna
  evidence: verification-gap: `FindInput.test.tsx` Harness ma własny `aria-busy`/`Brak wyników` double; `App` `aria-busy`/`ctaRef`/`role=alert` nie sprawdzane na real `App`; usunięcie `App.tsx` focus/error/skeleton nie psuje `npm test`

- source_spec: `C:/Users/admin/Documents/programowanie/speak epub/_bmad-output/implementation-artifacts/spec-1-3-powierzchnia-find-input-agregator-tabela-wyników.md`
  summary: shadcn ui/table.tsx martwy kod — ResultsTable nie używa wygenerowanego Table komponentu
  evidence: blind hunter + other findings: `src/components/ui/table.tsx` nowe Table/* nieimportowane w `ResultsTable.tsx:62` (raw `<table>`); plan Code Map zakładał użycie shadcn Table, zwiększa bundle bez testu `missing-adoption`

- source_spec: `C:/Users/admin/Documents/programowanie/speak epub/_bmad-output/implementation-artifacts/spec-1-4-powierzchnia-chapter-list-from-to-checkboxes.md`
  summary: handle_rpc listChapters kontrakt bez testów automatycznych — błąd serializacji/VALUE_ERROR/LIST_FAILED nie złapany
  evidence: verification-gap: brak testów `handle_rpc listChapters` w `tests/*.py`; `ChapterList.test.tsx` mockuje `callSidecar`, `test_novelphoenix.py` testuje adapter bezpośrednio — regresja `title —` fallback lub `result[]` vs `error` nie psuje testów

- source_spec: `C:/Users/admin/Documents/programowanie/speak epub/_bmad-output/implementation-artifacts/spec-1-4-powierzchnia-chapter-list-from-to-checkboxes.md`
  summary: useChapterList hook fetching/normalizacja/error mapping bez weryfikacji — brak hook testów
  evidence: verification-gap: `useChapterList` nie ma `renderHook` testów; `ChapterList.test.tsx` podaje static `chapters` 142, nigdy nie renderuje hooka — usunięcie `^https?://` guard, timeout 5s, sort nie psuje `npm test`

- source_spec: `C:/Users/admin/Documents/programowanie/speak epub/_bmad-output/implementation-artifacts/spec-1-4-powierzchnia-chapter-list-from-to-checkboxes.md`
  summary: App Chapter List integracja skeleton 6/error retry/retry reset/clamp nie weryfikowana — Harness vs real App
  evidence: verification-gap: brak `App` testu dla `data-testid=chapter-skeleton` 6 pulse, `role=alert` `chapterList.empty`+retry, reset `selected` na `selectedUrl` change; `ChapterList.test.tsx` Harness renderuje `ChapterList` bezpośrednio, `FindInput.test.tsx` nie dotyka chapter states

- source_spec: `C:/Users/admin/Documents/programowanie/speak epub/_bmad-output/implementation-artifacts/spec-1-4-powierzchnia-chapter-list-from-to-checkboxes.md`
  summary: RangeBar/ChapterList edge: empty string, swap od>do, ArrowUp/Enter/Shift+Space bez pinów, virtualized tylko warning
  evidence: verification-gap: `RangeBar` empty→no-op, `from 30→10` swap, `ArrowUp`/`Enter`/`Shift+Space` bulk via `bulkShift` nie testowane; `virtualized >500` tylko warning non-virtualized (Ask First defer) — usunięcie swap/bulk nie psuje `ChapterList.test.tsx`

- source_spec: `C:/Users/admin/Documents/programowanie/speak epub/_bmad-output/implementation-artifacts/spec-1-4-powierzchnia-chapter-list-from-to-checkboxes.md`
  summary: Selection persistence w Core vs GUI + virtualized windowing deferred per Ask First
  evidence: blind hunter + edge: `selected Set` w `App.tsx` nie w `store.json`/Core, reload → 0; `N>500` brak `react-window`/`@tanstack/virtual` — spec `Ask First` dodanie dep, subagent zostawił `virtualized-warning` fallback, nie blokuje `1-4` demo

## Deferred from: code review of spec-1-4-powierzchnia-chapter-list-from-to-checkboxes.md (2026-08-27)

- [Review][Defer] Virtualized >500 — only warning fallback, still renders `chapters.map` all rows, 800 rows freeze — spec Ask First `react-window/@tanstack/virtual` defer, `virtualized-warning` placeholder akceptowany — deferred, pre-existing [`src/components/ChapterList.tsx:132`] — evidence: blind-hunter+edge-case-hunter+acceptance-auditor; Attempted windowing deferred per Always Ask First dep outside React/TS/Vite/Tailwind/shadcn

## Deferred from: code review of spec-1-4-powierzchnia-chapter-list-from-to-checkboxes.md (2026-08-28)

- [Review][Defer] Virtualized >500 — only warning fallback, wciąż `chapters.map` wszystkie 800 rows freeze — spec Ask First `react-window/@tanstack/virtual` defer, `virtualized-warning` placeholder akceptowany — deferred, pre-existing [`src/components/ChapterList.tsx:1116`] — evidence: blind-hunter+acceptance-auditor
- [Review][Defer] `_CHAPTER_CACHE` vs Never:cache — lightweight chapter-list cache `Dict url→list` LRU 20, dokumentowany wyjątek `Never: cache (Epics2-3) → KEEP` polite cache dla FR2, nie TTL — deferred, pre-existing [`Speak-EPUB-1.0.0/core/config.py:59-62`] — evidence: acceptance-auditor flagged but re-review decision KEEP


- source_spec: C:/Users/admin/Documents/programowanie/speak epub/_bmad-output/implementation-artifacts/spec-2-1-polite-fetcher-cache-adaptive-429-resume.md
  summary: CACHE_ROOT no TTL/evict/clear, disk fill on 142+ chapters
  evidence: blind hunter core/fetch.py:406 CACHE_ROOT hardcoded Speak-EPUB-1.0.0/_cache no size limit/TTL/eviction; review 2-1 blind 2

- source_spec: C:/Users/admin/Documents/programowanie/speak epub/_bmad-output/implementation-artifacts/spec-2-1-polite-fetcher-cache-adaptive-429-resume.md
  summary: write_cache silent pass on ENOSPC/EACCES, no bubble to handle_rpc
  evidence: blind hunter core/fetch.py:459-464 read_cache swallows decode error; verification gap shows disk-full never surfaced

- source_spec: C:/Users/admin/Documents/programowanie/speak epub/_bmad-output/implementation-artifacts/spec-2-1-polite-fetcher-cache-adaptive-429-resume.md
  summary: FETCH_LOCK only in-process, no file lock for two app instances
  evidence: blind hunter core/fetch.py:768-778 threading.Lock + _FETCHING bool only; edge case FETCH_LOCK no timeout/try/finally

- source_spec: C:/Users/admin/Documents/programowanie/speak epub/_bmad-output/implementation-artifacts/spec-2-1-polite-fetcher-cache-adaptive-429-resume.md
  summary: Retry-After not handled for listChapters re-validate open-ended

- source_spec: `C:/Users/admin/Documents/programowanie/speak epub/_bmad-output/implementation-artifacts/spec-b1-land-remediation-patch.md`
  summary: Dead `plugin:shell|open` fallback in Result.tsx handleOpen is now unpermitted by scoped capabilities; opener allow-list policy for non-matching paths (e.g. custom outputDir names, uppercase .EPUB) needs a focused decision
  evidence: capabilities/default.json removed all shell:* permissions while src/components/Result.tsx:96 still invokes plugin:shell|open; primary opener path only covered by `**/*.epub` glob; verified no remaining plugin-shell imports in src/

- source_spec: `C:/Users/admin/Documents/programowanie/speak epub/_bmad-output/implementation-artifacts/spec-b1-land-remediation-patch.md`
  summary: Remove dead @tauri-apps/plugin-shell dependency from package.json (and docs/sidecar-fallback.md reference)
  evidence: verification-gap verified no src/ imports remain after shell permissions removal; dependency is dead weight shipped in dependencies

- source_spec: `C:/Users/admin/Documents/programowanie/speak epub/_bmad-output/implementation-artifacts/spec-b1-land-remediation-patch.md`
  summary: Add regression test pinning src-tauri/capabilities/default.json scoping (no shell:*, opener allow-list patterns) — the runtime permission grant itself is untestable in vitest
  evidence: verification-gap showed Result.test.tsx mocks invoke so permission regressions pass all gates; a config-assertion test would at least pin the JSON contract

- source_spec: `C:/Users/admin/Documents/programowanie/speak epub/_bmad-output/implementation-artifacts/spec-b1-land-remediation-patch.md`
  summary: core/http._get retries all 4xx (incl. 403) while fetch_one treats 403/404 as non-retryable — divergent retry policies need a deliberate decision
  evidence: core/http.py:49-52 retries any 4xx "for robustness"; parity with adapters/_http.py kept it as-is during land-and-green, but preview fallback can hammer a banning site with multi-second backoff

- source_spec: `C:/Users/admin/Documents/programowanie/speak epub/_bmad-output/implementation-artifacts/spec-b1-land-remediation-patch.md`
  summary: Backoff formula min(20, 2*attempt)+uniform(0.2,0.6) triplicated (core/fetch.py _backoff_delay, core/http.py inline x2, adapters/_http.py) — dedupe candidate for a Core bundle
  evidence: core/http.py cannot import adapters (AD-1) but could reuse core/fetch._backoff_delay; kept duplicated during B1 to avoid altering verified behavior

- source_spec: `C:/Users/admin/Documents/programowanie/speak epub/_bmad-output/implementation-artifacts/spec-b1-land-remediation-patch.md`
  summary: Cache-hit isolation-failure fallback asymmetry — html falls back to raw cached while text="" (logged "cache-hit isolation empty"); consider consistent fallback or document the security-conservative choice
  evidence: core/fetch.py:260 `text=cleaned_text or ""` with html fallback `cleaned_html or cached`; failure path logged at 253-257; edge only when whole clean pipeline fails, deliberate during B1 land-and-green

  evidence: blind hunter core/fetch.py:788 / config.py:212 open-ended listChapters 429 has no backoff; verification gap 2 shows no test for Retry-After on list refresh

- source_spec: C:/Users/admin/Documents/programowanie/speak epub/_bmad-output/implementation-artifacts/spec-2-1-polite-fetcher-cache-adaptive-429-resume.md
  summary: AbortSignal not interruptible, getCacheStatus extra network request just for badge
  evidence: blind hunter core/fetch.py:715 time.sleep not interruptible, sidecar port disconnect hang Edge 13, getCacheStatus eager listChapters with no politeness

- source_spec: C:/Users/admin/Documents/programowanie/speak epub/_bmad-output/implementation-artifacts/spec-2-1-polite-fetcher-cache-adaptive-429-resume.md
  summary: App queue slice 0,20 only, statuses for 21-100 invisible
  evidence: blind hunter src/App.tsx:1582 chapterList.slice(0,20) no virtualization, edge case App queue unbounded, verification gap badge only after Start

- source_spec: C:/Users/admin/Documents/programowanie/speak epub/_bmad-output/implementation-artifacts/spec-2-1-polite-fetcher-cache-adaptive-429-resume.md
  summary: _normalize_cache_key missing percent-encoding/default-port/path-case, duplicate cache
  evidence: blind hunter core/fetch.py:415-432 no percent-encoding, :80/:443, path case; edge case duplicate cache entries

## Deferred from: code review of spec-2-1-polite-fetcher-cache-adaptive-429-resume.md (2026-08-28)

- [Review][Defer] `_normalize_cache_key` brak NFC/IDNA/percent-encoding — duplicate cache dla `novel%2F123` [`Speak-EPUB-1.0.0/core/fetch.py:31`] — deferred, pre-existing — poza spec `host lower+port distinct+trailing dot+query/fragment stripped`, NFC/punycode/percent nie wymagane w 2.1.
- [Review][Defer] Dynamic `importlib` per RPC bez cache — duplikacja 4× `_il` [`Speak-EPUB-1.0.0/core/config.py:399`] — deferred, pre-existing — optymalizacja, nie funkcjonalny, `IMPORT_FAILED` path testowany.
- [Review][Defer] i18n Polish w Core (`pominięto`/`wykryto`) vs `t()` — [`Speak-EPUB-1.0.0/core/fetch.py:448`] — deferred, pre-existing — spec `Tasks` definiuje badge Polish w Core, `Never hardcode poza t()` Ask First dla TTS, akcept w 2.1.

- source_spec: _bmad-output/implementation-artifacts/spec-2-2-content-boundary-selektory-per-adapter-heuristic-preview-kor.md
  summary: Preview dangerouslySetInnerHTML bez sanitizacji — XSS w webview
  evidence: blind hunter src/components/Preview.tsx:344 dangerouslySetInnerHTML renderuje raw HTML bez DOMPurify allowlist; verification-gap nie wykrywa bo Preview.test mockuje sidecar

- source_spec: _bmad-output/implementation-artifacts/spec-2-2-content-boundary-selektory-per-adapter-heuristic-preview-kor.md
  summary: save_overrides atomic bez fsync i lock — crash zostawia truncated JSON
  evidence: blind hunter core/clean.py:77 tmp.replace bez os.fsync/lock; edge-case-hunter wskazał brak fsync przy crash

- source_spec: _bmad-output/implementation-artifacts/spec-2-2-content-boundary-selektory-per-adapter-heuristic-preview-kor.md
  summary: App preview wiring i sidecar wrappers pokryte tylko mockami — brak realnego testu integracyjnego
  evidence: verification-gap 3+4 — sidecar preview/getSelectors i App handlePreview testowane tylko przez vi.mock, brak testu spy na invoke/callSidecar payload trim

## Deferred from: code review of spec-3-3-ffmpeg-merge-per-chapter-single-m4b-z-markerami.md (2026-08-29)

- [Review][Defer] Header comment drift — core/tts.py:14 "Pure: no subprocess" a dodano shutil/subprocess [`Speak-EPUB-1.0.0/core/tts.py:14`] — deferred, pre-existing — evidence: acceptance-auditor info; fix: zaktualizować komentarz nagłówka
- [Review][Defer] Empty audio_entries → build_m4b woła ffmpeg z pustym concat — [`Speak-EPUB-1.0.0/core/tts.py:444`] — deferred, pre-existing — evidence: spec-3-3:73 defer low "empty plans → build_m4b creates empty concat and ffmpeg errors"
- [Review][Defer] Brak timeout na edge_tts Communicate.save — [`Speak-EPUB-1.0.0/core/tts.py:192`] — deferred, pre-existing — evidence: spec-3-3 deferred medium "No timeout on edge_tts save still present after merge"
