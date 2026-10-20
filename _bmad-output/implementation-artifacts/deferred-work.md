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

- [Review][Resolved] Virtualized >500 — only warning fallback, still renders `chapters.map` all rows, 800 rows freeze — spec Ask First `react-window/@tanstack/virtual` defer, `virtualized-warning` placeholder akceptowany — deferred, pre-existing [`src/components/ChapterList.tsx:132`] — evidence: blind-hunter+edge-case-hunter+acceptance-auditor; Attempted windowing deferred per Always Ask First dep outside React/TS/Vite/Tailwind/shadcn — RESOLVED 2026-10-20 (review part 3)

## Deferred from: code review of spec-1-4-powierzchnia-chapter-list-from-to-checkboxes.md (2026-08-28)

- [Review][Resolved] Virtualized >500 — only warning fallback, wciąż `chapters.map` wszystkie 800 rows freeze — spec Ask First `react-window/@tanstack/virtual` defer, `virtualized-warning` placeholder akceptowany — deferred, pre-existing [`src/components/ChapterList.tsx:1116`] — evidence: blind-hunter+acceptance-auditor — RESOLVED 2026-10-20 (review part 3)
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
- [Review][Resolved] i18n Polish w Core (`pominięto`/`wykryto`) vs `t()` — [`Speak-EPUB-1.0.0/core/fetch.py:448`] — deferred, pre-existing — spec `Tasks` definiuje badge Polish w Core, `Never hardcode poza t()` Ask First dla TTS, akcept w 2.1. — RESOLVED 2026-10-20 (review part 3)

- source_spec: _bmad-output/implementation-artifacts/spec-2-2-content-boundary-selektory-per-adapter-heuristic-preview-kor.md
  summary: Preview dangerouslySetInnerHTML bez sanitizacji — XSS w webview
  evidence: blind hunter src/components/Preview.tsx:344 dangerouslySetInnerHTML renderuje raw HTML bez DOMPurify allowlist; verification-gap nie wykrywa bo Preview.test mockuje sidecar
  resolved: safePreviewHtml + DOMPurify (Preview.tsx, zarówno oryginalny jak i oczyszczony HTML przechodzą przez sanitizację) z testami pinującymi R3 (URI/tag policy) w Preview.test.tsx

- source_spec: _bmad-output/implementation-artifacts/spec-2-2-content-boundary-selektory-per-adapter-heuristic-preview-kor.md
  summary: save_overrides atomic bez fsync i lock — crash zostawia truncated JSON
  evidence: blind hunter core/clean.py:77 tmp.replace bez os.fsync/lock; edge-case-hunter wskazał brak fsync przy crash

- source_spec: _bmad-output/implementation-artifacts/spec-2-2-content-boundary-selektory-per-adapter-heuristic-preview-kor.md
  summary: App preview wiring i sidecar wrappers pokryte tylko mockami — brak realnego testu integracyjnego
  evidence: verification-gap 3+4 — sidecar preview/getSelectors i App handlePreview testowane tylko przez vi.mock, brak testu spy na invoke/callSidecar payload trim

## Deferred from: code review of spec-3-3-ffmpeg-merge-per-chapter-single-m4b-z-markerami.md (2026-08-29)

- [Review][Resolved] Header comment drift — core/tts.py:14 "Pure: no subprocess" a dodano shutil/subprocess [`Speak-EPUB-1.0.0/core/tts.py:14`] — deferred, pre-existing — evidence: acceptance-auditor info; fix: zaktualizować komentarz nagłówka — RESOLVED 2026-10-20 (review part 3)
- [Review][Resolved] Empty audio_entries → build_m4b woła ffmpeg z pustym concat — [`Speak-EPUB-1.0.0/core/tts.py:444`] — deferred, pre-existing — evidence: spec-3-3:73 defer low "empty plans → build_m4b creates empty concat and ffmpeg errors" — RESOLVED 2026-10-20 (review part 3)
- [Review][Resolved] Brak timeout na edge_tts Communicate.save — [`Speak-EPUB-1.0.0/core/tts.py:192`] — RESOLVED 2026-10-18 — production test zamarł na WebSocket stallu (21 parts, +0 przez 90 s); run_tts_job teraz asyncio.wait_for(save, max(240, min(600, len(text)*0.3))) z retry loop. — RESOLVED 2026-10-20 (review part 3)

## Deferred from: code review (2026-10-16)

- [Review][Defer] runTtsJobs (legacy RPC) nie przekazuje rate/engine/local_voice/adaptive do run_part_jobs [core/config.py:1026-1045] — deferred, pre-existing — brak konsumenta w src/ i testach; podłączyć, gdy GUI zacznie używać tego wejścia.


## Deferred from: code review round 2 (2026-10-16)

- [Review][Resolved] Zmiana --rate nie regeneruje istniejących MP3 (rate nie jest częścią tożsamości resume) [core/tts.py:build_generation_plan] — RESOLVED 2026-10-18 — build-identity manifest `.speak-epub-build.json` (BUILD_IDENTITY_KEYS zawiera rate/voice/engine/local_voice/dialogue_voice/normalize_audio/trim_silence) wymusza regenerację przy zmianie; decision: auto-regeneracja z wipe. — RESOLVED 2026-10-20 (review part 3)
- [Review][Resolved] mkdir output swallow w tts_text_to_mp3_local (pre-existing pattern) [core/tts_local.py] — deferred, pre-existing — błąd uprawnień powierzchnią później; nie ruszane w tej rundzie. — RESOLVED 2026-10-20 (review part 3)

## Deferred from: code review (2026-10-19)

Review pełnego backendu `core/` (8619 linii, 12 warstw: blind-hunter / edge-case-hunter / verification-gap × 4 grupy plików), tryb no-spec, każdy finding zweryfikowany odczytem kodu i realnych call-site'ów.

- [Review][Defer] Politeness nie jest w Core — ścieżka fetch deleguje do `adapter.fetchChapter`, `core/http.py` używany tylko w fallbacku preview [core/fetch.py:9-18, core/http.py:3-4] — deferred, pre-existing — kontrakt "AD-3 politeness owned by Core" nie jest egzekwowany; polityki już się rozjechały (patrz patch: 4xx policy).
- [Review][Defer] Core importuje konkretny adapter (naruszenie kontraktu core→ports→adapter; importlinter daje fałszywe poczucie bezpieczeństwa) [core/audio.py:186-194, core/epub.py:596,706] — deferred, pre-existing — wymaga nowej metody portu (`resolve_selectors`).
- [Review][Defer] Brak obsługi robots.txt i brak limitu per-host [core/fetch.py:1-8] — deferred, pre-existing — dziś jedno źródło i globalny delay 3–5 s.
- [Review][Resolved] loudnorm jednoprzebiegowy (dynamic mode, bez pomiaru i `linear=true`) [core/tts.py:703] — deferred, pre-existing — ffmpeg dokumentuje niedokładność trybu dynamic; dwuprzebiegowy pomiar to większa zmiana. — RESOLVED 2026-10-20 (review part 3)
- [Review][Resolved] `max_chars` > 5000 tylko ostrzega [core/tts.py:425-426] — deferred, pre-existing — GUI klamruje 500..5000, tylko CLI przepuszcza. — RESOLVED 2026-10-20 (review part 3)
- [Review][Resolved] PID w lockfile nigdy nie jest czytany (żywotność rozstrzyga sam mtime + heartbeat) [core/tts.py:83, 96-111] — deferred, pre-existing — heartbeat odświeża mtime co 60 s, próg 600 s. — RESOLVED 2026-10-20 (review part 3)
- [Review][Resolved] AdaptiveGate budzi tylko jednego czekającego na zmianę limitu [core/tts.py:1154-1159] — deferred, pre-existing — to latency, nie deadlock (anulowany future nie zgubi wake-upa). — RESOLVED 2026-10-20 (review part 3)
- [Review][Resolved] Klucz cache pomija query string [core/fetch.py:53-72, core/config.py:103] — deferred, pre-existing — obecny adapter stripuje query z href, więc dziś bez skutku; zagrożenie dla przyszłych witryn z `?chapter=N`. — RESOLVED 2026-10-20 (review part 3)
- [Review][Resolved] `runTtsJobs` (legacy RPC): 300 s timeout to dead code, malformed joby dropowane po cichu, `output_path` bez walidacji [core/config.py:919-1065] — deferred, pre-existing — brak konsumenta w `src/` i testach. — RESOLVED 2026-10-20 (review part 3)
- [Review][Resolved] Ścieżki tylko-in-process w `core/audio.py` (limit 1800 s, wątek przeżywa TimeoutError, pętla zdarzeń nie domknięta) [core/audio.py:546-579] — deferred, pre-existing — GUI spawnuje świeżego `python -c` per RPC, CLI nie woła `build_audio`. — RESOLVED 2026-10-20 (review part 3)
- [Review][Resolved] `getEpubStatus` dopasowuje plik fuzzy scoringiem + inline `run_epubcheck` [core/config.py:2151-2187] — deferred, pre-existing — metoda nieużywana przez GUI. — RESOLVED 2026-10-20 (review part 3)
- [Review][Defer] `getCacheStatus` robi pełne listowanie sieciowe mimo komentarza "diff without fetching" [core/config.py:679-691] — deferred, pre-existing — nieużywane przez GUI.
- [Review][Resolved] Polskie stringi zaszyte w Core + GUI pattern-matchuje polskie słowa do badge [core/config.py:740-742, core/fetch.py:794-800, src/hooks/useFetcher.ts:125,255] — deferred, pre-existing — pełna i18n to osobny temat. — RESOLVED 2026-10-20 (review part 3)
- [Review][Resolved] Reguła zamiany from/to zaimplementowana 4× na różne sposoby [core/config.py:1097, 1166, 1829, 720] — deferred, pre-existing — dziś zgodne, ryzyko rozjazdu przy zmianie jednej kopii. — RESOLVED 2026-10-20 (review part 3)
- [Review][Resolved] Allowlista hostów skopiowana 9× [core/config.py:344, 517, 1312, 1347, 1504, 1550, 1764, 1920, 2374] — deferred, pre-existing — dziś wszystkie kopie akceptują ten sam zbiór hostów; koszt to ryzyko konserwacji. — RESOLVED 2026-10-20 (review part 3)
- [Review][Resolved] Brak logowania strukturalnego po stronie sidecara (brak `import logging`) [core/config.py:7-12] — deferred, pre-existing — warstwa Rust drainuje stderr do konsoli, brak pliku logu. — RESOLVED 2026-10-20 (review part 3)
- [Review][Resolved] `saveSelectors` akceptuje dowolny syntaktycznie poprawny selektor [core/config.py:1519-1526] — deferred, pre-existing — GUI łagodzi to live podglądem przed zapisem. — RESOLVED 2026-10-20 (review part 3)
- [Review][Resolved] `previewChapter` zwraca nieobcięty `originalHtml` [core/config.py:1480-1483] — deferred, pre-existing — realne ryzyko to pamięć/UI, nie poprawność. — RESOLVED 2026-10-20 (review part 3)
- [Review][Resolved] Błąd pojedynczego rozdziału raportowany jako `LIST_FAILED` (adapter używa `FETCH_FAILED`) [core/fetch.py:486, 522, core/ports.py:52-57] — deferred, pre-existing — taksonomia kodów błędów nie ma jednego źródła. — RESOLVED 2026-10-20 (review part 3)
- [Review][Resolved] `AdapterError` nie ma pola na szczegóły (workaround: monkey-patch `err.missing`) [core/ports.py:52-57, core/audio.py:152-156] — deferred, pre-existing — strukturalny brak DTO, nie bug wywołania. — RESOLVED 2026-10-20 (review part 3)
- [Review][Resolved] Modele głosów Piper bez sumy kontrolnej / podpisu [core/tts_local.py:240-299] — deferred, pre-existing — mirror HuggingFace, brak oficjalnych checksum w źródle. — RESOLVED 2026-10-20 (review part 3)
- [Review][Resolved] Nieeksponowane knoby Piper (`sentence_silence`, `noise_scale`, `noise_w`) [core/tts_local.py:430] — deferred, pre-existing — `length_scale` wystarcza do bieżących potrzeb. — RESOLVED 2026-10-20 (review part 3)
- [Review][Resolved] `prune_cache(ttl_days=0)` kasuje cały cache, wartość ujemna wyłącza TTL, `cover.txt` zostaje osierocony [core/fetch.py:180-190] — deferred, pre-existing — semantyka wywołania, nie ścieżka produkcyjna. — RESOLVED 2026-10-20 (review part 3)
- [Review][Resolved] `core/ports.py`: `ChapterInfo.title` wymagane, choć warstwy używają fallbacków; `Selectors` nie normalizuje białych znaków [core/ports.py:18-23, 36-40] — deferred, pre-existing — konsumenci neutralizują oba przypadki. — RESOLVED 2026-10-20 (review part 3)

## Deferred from: code review — part 2 (2026-10-19)

Pakiety 1–4 + 12 (dane/atomowość/gates + testy) zaimplementowane w tym cyklu; pozostałe findingi z tego samego review czekają na kolejną partię. Wszystkie zweryfikowane odczytem kodu i realnych call-site'ów.

### Status po implementacji (2026-10-19, part 2)

Pakiety 5, 6, 7, 8, 9, 10, 11, 13, 14 zaimplementowane i przypięte testami (507 passed, vitest 215, tsc clean, smoke test na realnej książce). Wszystkie wpisy poniżej oznaczone jako „do naprawy" w części 2 są **rozwiązane**; pozostają tylko pozycje strukturalne, których świadomie nie ruszałem.

### Pakiety 5, 13, 14 — liczniki, logi, hygiene, wynik builda

- [Review][Resolved] `logs.append` zamiast `_emit_log` — diagnostyki (np. "chapter skipped", "boilerplate templates") nigdy nie docierają do logu GUI [core/audio.py:255, 260, 463, 466, 472, 475, 482, 641] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] `print` zamiast callbacku `on_log` w `_ensure_valid_or_drop` — GUI nie widzi powodu re-syntezy [core/tts.py:363] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] Title part numerowany 0, ale liczony w part_count — UI pokazuje "part 0/3" [core/tts.py:869-870] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] Planowanie segmentów dialogowych dla silnika local, który ignoruje `PartJob.voice` — marnuje pracę i myli metadane [core/tts.py:804-808 vs 1466-1471] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] `ADAPTIVE_MAX_PARALLEL = 12` i dopuszczalne `parallel` do 6 — Edge TTS throttluje powyżej 3 [core/tts.py:1130, core/audio.py:388] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] Wynik `build_audio` nie zwraca engine/rate/filtrom/czasu trwania/rozmiaru partów [core/audio.py:645-659] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] M4B z aplikacji desktopowej bez okładki (GUI zna URL okładki) [core/audio.py:609-618] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] `bool("false")` = True dla flag ze store (normalize/trim/keepMP3) [core/audio.py:384-386, 453, 631] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] `keepMP3=false` usuwa pliki, ale `chapters[].path` wskazuje je dalej [core/audio.py:600-602, 634-641] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] `coverUrl` >500 znaków obcinany w RPC, w `core/epub.py` dropowany — niespójna polityka [core/config.py:1798-1799] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] `user_output_base` hardcoduje angielskie "Documents" — na zlokalizowanym Windowsie wyjście ląduje w złym katalogu [core/tts.py:157-160] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] `Dict` użyte bez importu; `__all__` z duplikatami i brakami; martwe importy; mylący docstring "Pure" [core/tts.py:606, 2071-2103, 14, 79; core/config.py:12] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] `extra_params` nigdy nie używany; martwy branch `isinstance(chunks, bytes)`; dwa formaty licznika retry; martwe ramię w mapowaniu błędów [core/epub.py:370, 902-909; core/fetch.py:437-441 vs 505-548, 680-682] — RESOLVED 2026-10-19 (review part 2)

### Pakiet 6 — filtry

- [Review][Resolved] Okna head/tail boilerplate zachodzą na siebie przy rozdziale <30 linii → cały rozdział może zniknąć [core/filters.py:123-126] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] Auto-wykryty boilerplate bez weta — legitytne "The End" w 2 rozdziałach jest usuwane [core/filters.py:135-149] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] Zduplikowany tekst z zagnieżdżonych bloków (toolbar linków mówiony 2×) [core/filters.py:54-61] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] Jeden filtr może skasować cały content-wrapper (chronione tylko `div#chapter-content` i div z `<p>`) [core/filters.py:284-293] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] Dwie kanonizacje `isRegex` (`{"type":"regex"}` / `"1"` vs `sanitize_filters`) [core/filters.py:157 vs 350-351] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] `except` po nieudanym imporcie bs4 woła `BeautifulSoup` → NameError [core/filters.py:270-276] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] Błędy filtrów połykane bez logu (audio i EPUB) [core/audio.py:252-257, core/epub.py:803-806] — RESOLVED 2026-10-19 (review part 2)

### Pakiet 7 — clean.py

- [Review][Resolved] `load_overrides` KASUJE plik ustawień przy jakimkolwiek błędzie odczytu [core/clean.py:115-120] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] Katalog overrides w drzewie pakietu → read-only w Program Files, utrata po reinstalacji [core/clean.py:52] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] Override całkowicie zastępuje domyślny `start` adaptera → pusty rozdział [core/clean.py:144-158] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] Granica `end` ignorowana w fallbacku heurystycznym; sibling-walk połyka ogon strony; komentarz o truncacji niezgodny z kodem [core/clean.py:214-279, 241-258, 231-234] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] `clean_html` bez diagnostyki — fallback na całe body narruje nawigację jako rozdział [core/clean.py:190-314] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] Brak `header/footer/figure/figcaption` w noise tags; `a[rel='next']` case-sensitive [core/clean.py:22-40] — RESOLVED 2026-10-19 (review part 2)

### Pakiet 8 — EPUB

- [Review][Resolved] Nieważny EPUB publikowany i nigdy nie usuwany — „bramka" tylko opisuje, nie bramkuje [core/epub.py:1046-1059] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] Pusty rozdział zapisywany do EPUB-a (ścieżka audio go pomija) [core/epub.py:810-812] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] Fallback pustego rozdziału wstawia tekst sprzed filtrowania [core/epub.py:812] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] EPUB nie jest samowystarczalny — przy nieudanym pobraniu zostaje zdalne `src` [core/epub.py:310-316] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] Pobieranie obrazów bez allowlisty i z przekierowaniami (SSRF na adresy wewnętrzne) [core/epub.py:302-311] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] WebP zapisywany jako `cover.jpg` z media type `image/jpg` [core/epub.py:937-961] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] Stała nazwa pliku `.tmp` → dwa równoległe buildy kolidują [core/epub.py:1044-1047] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] Język EPUB hardcodowany na "en" [core/epub.py:877, 1026] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] `CACHE_MISS` z `build_epub` nie niesie listy brakujących rozdziałów [core/epub.py:676-694, core/ports.py:52-57] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] `build_epub` bez postępu → sidecar ubijany po 300 s ciszy [core/epub.py:653, src-tauri/src/lib.rs:303] — RESOLVED 2026-10-19 (review part 2)

### Pakiet 9 — fetch/cache

- [Review][Resolved] Strona z captcha/blokadą trafia do cache na stałe i jest odtwarzana przy każdym runie [core/fetch.py:91, 449-455] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] `prune_cache` nigdy niewołany — cache rośnie bez limitu, TTL nie działa [core/fetch.py:138-217] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] `write_cache` rzuca ValueError → `write_cover` pomijany, wpis cache ginie [core/fetch.py:449-455] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] `Retry-After` bez limitu → godzina zablokowanej kolejki [core/fetch.py:555-573] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] Tier "safe" po 429 nigdy nie wraca do "polite" (10 s/opóźnienie do końca runu) [core/fetch.py:421, 809] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] Badge pokazuje zakres liczony od 1 zamiast od `from_idx` [core/fetch.py:794-800] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] Numeracja rozdziałów pozycyjna zamiast prawdziwych indeksów [core/fetch.py:812-820] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] `from`/`to` ignorowane, gdy caller podaje listę URL-i [core/fetch.py:760-762] — RESOLVED 2026-10-19 (review part 2)

### Pakiet 10 — ffmpeg_setup / tts_local

- [Review][Resolved] `http.client.IncompleteRead` nie złapany → wyjątek ucieka z `ensure_ffmpeg` [core/ffmpeg_setup.py:176] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] Istniejący `bin/ffmpeg` adoptowany bez weryfikacji [core/ffmpeg_setup.py:203-207] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] Ekstrakcja wprost do żywego `bin/` — brak stagingu i atomic publish [core/ffmpeg_setup.py:134-164] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] Sukces bez ffprobe → M4B pomijane, gate truncacji wyłączony [core/ffmpeg_setup.py:185-191] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] `ensure_ffmpeg` z wątków workerów: globalny PATH i wspólny katalog bez blokady [core/tts_local.py:416-423, core/ffmpeg_setup.py:83-88] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] Pobieranie bez deadline'u całkowitego (tylko per-socket) [core/ffmpeg_setup.py:119-131] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] Clamp rate local (-25%) rozjeżdża się z Edge (-100%) [core/tts_local.py:357] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] `.onnx.json` nigdy nie walidowany — uszkodzony config wybucha przy syntezie [core/tts_local.py:104-108] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] `_piper_available()` sprawdza tylko spek modułu, nie importuje piper/onnxruntime [core/tts_local.py:76-81] — RESOLVED 2026-10-19 (review part 2)

### Pakiet 11 — config.py / store

- [Review][Resolved] Ścieżka `store.json` zależy od CWD procesu (może w read-only katalog instalacji) [core/config.py:163-178] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] `save_store`: read-modify-write ze stałym `.tmp` → utrata update'ów przy równoległych setStore [core/config.py:195-214] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] Uszkodzony store cicho wraca do defaultsów (całe ustawienia znikają) [core/config.py:185-191] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] `search` połyka każdy błąd → pusta lista zamiast komunikatu [core/config.py:285-295] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] `setSelection` po cichu odrzuca non-http URL, ale odpowiada "saved" [core/config.py:1178-1188] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] Lista `selection` bez limitu długości i zakresu [core/config.py:1124-1133] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] `previewVoice` bez timeoutu — wiszący Piper blokuje cały RPC [core/config.py:2316-2322] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] Rate: preview normalizuje bzdury do "+0%", buildAudio je odrzuca [core/config.py:2262-2267 vs 2445-2451] — RESOLVED 2026-10-19 (review part 2)
- [Review][Resolved] Pusty `localVoice` (domyślny) vs nieobecny — GUI nie może odróżnić [src/lib/sidecar.ts:661-664, core/config.py:2273-2274] — RESOLVED 2026-10-19 (review part 2)

## Deferred from: code review — part 3 (2026-10-20)

Pakiety 5–14 z review backendu domknięte. Zamknięte pozycje (oznaczone w sekcji
powyżej jako RESOLVED):

- **Pakiety 5/13/14**: logi do GUI, numeracja części (tytuł = 1), brak dzielenia na dialog
  dla silnika local, `ADAPTIVE_MAX_PARALLEL` 12 → 3, `parallel` ≤ 3, wynik builda z
  engine/rate/filtrom/czasem, okładka w M4B, `bool("false")` → prawdziwy parser,
  `keepMP3` nie wskazuje usuniętych plików, `coverUrl` > 500 znaków odrzucone (nie
  obcinane), katalog wyjściowy zgodny z lokalizacją, hygiene (importy, `__all__`,
  docstring „Pure").
- **Pakiet 6 (filtry)**: strefy head/tail nie nachodzą na siebie, auto-boilerplate
  raportowany i zabezpieczony limitem 30 % długiego rozdziału, duplikat tekstu
  z zagnieżdżonych bloków zniesiony, content-wrapper chroniony, jedna kanonizacja
  `isRegex`, brak NameError w fallbackzie bs4, błędy filtrów logowane.
- **Pakiet 7 (clean.py)**: błąd odczytu nie usuwa overrides, overrides w katalogu
  użytkownika, override nie gubi domyślnego `start`, granica `end` działa w fallbacku,
  sibling-walk nie połyka ogona strony, fallback całej strony jest raportowany.
- **Pakiet 8 (EPUB)**: nieważny EPUB jest odsuwany, pusty rozdział pomijany, brak
  tekstu sprzed filtra, allowlista obrazów (SSRF), webp zachowuje format, unikalny
  `.tmp`, język w parametrze, `missing` w błędzie, postęp do GUI.
- **Pakiet 9 (fetch/cache)**: query w kluczu cache, semantyka `prune_cache` + sieroty,
  `FETCH_FAILED` dla body rozdziału, badge strukturalny (bez dopasowywania polskich słów),
  cache z limitem rozmiaru/TTL faktycznie stosowany.
- **Pakiet 10 (ffmpeg/tts_local)**: `IncompleteRead` obsłużony, istniejąca binaria
  weryfikowana, staging instalacji, `ffprobe` wymagany, wykrywanie providera CUDA +
  fallback na CPU, blokada rate, deadline pobierania, walidacja `.onnx.json`, sha256 modelu.
- **Pakiet 11 (config/store)**: store w katalogu użytkownika, atomowy zapis,
  uszkodzony store raportowany, `search` zwraca błąd, `setSelection` odrzuca
  nie-http URL, lista selection ma limit, preview ma timeout, `localVoice` pusty znaczy
  „głos domyślny", `AdapterError.details`, logowanie do `app.log`.
- **Pakiet 14**: badge formatowany z danych (pl/en), lista rozdziałów renderuje się
  blokami po 100 wierszy (przycisk „pokaż więcej" zamiast „pokaż wszystko").

Nowe w tej rundzie: **GPU dla Pipera** (`--cuda` w CLI, przełącznik w Ustawieniach,
`use_cuda` z automatycznym fallbackiem na CPU) oraz **self-contained CLI** (pakiet
0,13 MB, runtime pobierany raz).

Świadomie nietknięte (wymagają decyzji architektonicznej): `robots.txt` (ryzyko
zablokowania scrapera), przeniesienie politeness do Core (dziś transport należy do
adaptera), import konkretnego adaptera w Core (kontrakt ports), `getEpubStatus`/
`getCacheStatus` bez zmiany API.
