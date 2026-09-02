---
title: 'Powierzchnia Find — input + agregator + tabela wyników'
type: 'feature'
created: '2026-08-27'
status: 'done'
baseline_commit: '678e0f1807d2541d54646aaed4d7a14c6a3bbc58'
review_loop_iteration: 0
context:
  - _bmad-output/specs/spec-speak-epub/SPEC.md
  - _bmad-output/planning-artifacts/architecture/architecture-speak-epub-2026-08-27/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/ux-designs/ux-speak-epub-2026-08-27/DESIGN.md
  - _bmad-output/implementation-artifacts/epic-1-context.md
  - _bmad-output/planning-artifacts/epics.md
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `src/App.tsx:107` to dashed placeholder — brak `FindInput` 44px i `ResultsTable` `site|title|chapters|link`; reader nie może wkleić URL/tytułu i wybrać źródła.

**Approach:** Zbudować Find: `FindInput` 44px clear+paste debounced 400ms via `core/aggregator.py:26` przez `handle_rpc search`, oraz `ResultsTable` hover `muted` selected `accent left 2px + #EFF3FF` plus skeleton/empty i klawiatura roving tabindex — mock wystarczy, lista rozdziałów w 1.4.

## Boundaries & Constraints

**Always:** `GUI→Core→Port→Adapter`; tokens `DESIGN.md:11` jako CSS vars (`--ring #2B5CE6`, `rounded.md 8px`, `mono JetBrains 12`) i Tailwind; input `h-11 44px` `focus:ring-2 ring` AA; tabela hover `bg-muted #F1F3F5` selected `border-l-2 border-accent bg-[#EFF3FF]` (`DESIGN.md:185`); skeleton 3 rows `aria-busy` while searching, no-results `display-sm` + CTA `Wklej URL`; wiersz klikalny `Enter` wybiera; `^https?://` → URL mode (guess_adapter) else tytuł → aggregator; `t()` bez hardcode.

**Ask First:** Zmiana `ScraperPort`/`aggregator` kontraktu lub `handle_rpc` transport poza `python_sidecar_call`; deps poza React/TS/Vite/Tailwind/shadcn + `requests/bs4/lxml`.

**Never:** Lista rozdziałów Range/checkboxy (1.4), Preview (2.2), kolejka/M4B, cache/resume (2.1), parallel scrape, drag/infinite scroll, hardcode strings, manual dark toggle.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Title debounced | typing `lord myst` debounce 400ms | Po 400ms `callSidecar("search",{title})` <5s parallel via `aggregator.py:26`; skeleton 3 `animate-pulse` + `Przeszukuję NovelPhoenix…` | 4xx/5xx/timeout → `[]` toast `search failed` no crash |
| Search hit | `Lord of Mysteries` | Tabela `site|title|chapters|link` hover `muted` selected `accent left 2px + #EFF3FF`, wiersz klikalny, `Enter` wybiera → `selectedUrl` | `[]` → no-results |
| No results | `zzzz_no_match` | `display-sm Brak wyników dla ‘X’` + CTA `Wklej URL` + link fallback | N/A |
| URL paste | `https://www.novelphoenix.com/book/123` | `^https?://` → walidacja URL, `guess_adapter` → `listChaptersCount` mock single row, bez agregatora | `guess None` → `—` nie blokuje |
| Validation | `""`/whitespace/`len>300` | `ValueError` bez sieci, truncate `>300→200` przed request | inline helper |
| Keyboard | Tabela focus | `Tab input→table→CTA`, `arrows` roving tabindex, `Space` toggle, `Enter` Wybierz, ring `2px` AA | `Esc` nie zamyka |
| Skeleton | searching true | 3 rows `h-4 bg-muted` sticky header `aria-busy` | N/A |

</frozen-after-approval>

## Code Map

- `src/App.tsx:29-113` — **WIRED** — replace `placeholder.discovery` `App.tsx:107` with `FindInput`+`ResultsTable` state `selectedUrl`/`searchResults`; keep locale `App.tsx:23` and token demo `App.tsx:53`
- `src/lib/sidecar.ts:25-42` — **REUSE** — `callSidecar` `python_sidecar_call` + fallback `http://localhost:17381/rpc` + id check `sidecar.ts:55`; keep `ping` `sidecar.ts:70`
- `Speak-EPUB-1.0.0/core/aggregator.py:26` — **CONSUMED** — `search_all` parallel 5s dedupe `aggregator.py:26`
- `Speak-EPUB-1.0.0/core/config.py:115-135` — **EXTEND** — `handle_rpc` `ping/hello` `config.py:126`; dodać `elif method=="search":` walidacja truncate 200 → `search_all` + `NovelPhoenixAdapter` (lokalny import, udokumentować wyjątek `.importlinter` dla `core.config→adapters`)
- `Speak-EPUB-1.0.0/adapters/novelphoenix.py:31` — **REUSE** — `search` już działa
- `Speak-EPUB-1.0.0/adapters/base.py:19` — **REUSE** — `guess_adapter` host-suffix `base.py:33`
- `src/components/FindInput.tsx` — **NEW** — `h-11 44px rounded-md border-input focus:ring-2 ring`, clear `x` + paste, `t("find.placeholder")`, debounce 400ms
- `src/components/ResultsTable.tsx` — **NEW** — shadcn `Table` `site|title|chapters|link` `body 14px`, hover `bg-muted`, selected `border-l-2 border-accent bg-[#EFF3FF]` `DESIGN.md:185`, `role=button` `tabIndex 0` `aria-selected`
- `src/hooks/useDebouncedSearch.ts` — **NEW** — `useDebouncedValue(query,400)` + `callSidecar` `AbortController` 5s, URL detect `^https?://`, `searching`/`results`/`error`
- `src/i18n/locales/en.json` + `pl.json` — **EXTEND** — `find.placeholder/searching/noResults/cta`, `results.headers.*`, `toast.searchFailed`
- `src/styles/globals.css:3` + `tokens.ts:6` — **READ-ONLY** — vars `DESIGN.md:11` już
- `package.json` — **READ-ONLY** — React18/TS5/Vite6/Tailwind4/shadcn

## Tasks & Acceptance

**Execution:**
- [x] `Speak-EPUB-1.0.0/core/config.py` — dodać `search` w `handle_rpc` (i `listChaptersCount` dla URL mode) — walidacja truncate 200, lokalny import `search_all`+`NovelPhoenixAdapter`, zwrot `{"result":[...]}`
- [x] `src/hooks/useDebouncedSearch.ts` — NEW debounced 400ms, `callSidecar` 5s timeout, URL detect, cleanup unmount
- [x] `src/components/FindInput.tsx` — NEW 44px `h-11 rounded-md border-input focus:ring-2 ring` clear+paste `t()` debounce
- [x] `src/components/ResultsTable.tsx` — NEW tabela hover `muted` selected `accent #EFF3FF` `DESIGN.md:185`, row clickable roving tabindex Enter
- [x] `src/App.tsx` — wire `FindInput`+`ResultsTable` state, skeleton 3 `aria-busy` while searching, no-results `display-sm` + CTA
- [x] `src/i18n/locales/en.json` + `pl.json` — dodać `find.*` `results.headers.*` `toast.searchFailed`
- [x] `src/components/FindInput.test.tsx` — mocked `callSidecar`: debounce→search raz, skeleton busy, no-results CTA, keyboard Enter wybiera

**Acceptance Criteria:**
- Given Find focused, when wpisuję `Lord of Mysteries` debounced 400ms, then skeleton 3 `aria-busy` + `Przeszukuję…`, po <5s tabela hover `muted` selected `accent left 2px + #EFF3FF`, `Enter` wybiera `selectedUrl`.
- Given no results `zzzz_no_match`, when search pusto, then `Brak wyników dla ‘X’` + CTA `Wklej URL` + link fallback, focus w CTA.
- Given tabela 2 wiersze, when `Tab→arrows→Enter/Space`, then roving tabindex, `Enter` Wybierz, ring `2px` AA, `aria-selected` true.
- Given `handle_rpc search` title `Lord`, when `callSidecar("search",{title})` via `sidecar.ts:25`, then `SearchResult[]` `site|title|chapters|link` <5s parallel, `""`→`ValueError` bez sieci, `>300→200`.
- Given URL `https://www.novelphoenix.com/book/123`, when wklejony, then nie woła aggregatora, waliduje URL i pokazuje single row bez błędu.

## Spec Change Log


## Verification

**Commands:**
- `npm run build` -- Vite build success, `FindInput`/`ResultsTable` included, `var(--ring)` present
- `cargo check --manifest-path src-tauri/Cargo.toml` -- Tauri 2.11.5 resolve OK
- `Speak-EPUB-1.0.0/venv/Scripts/python.exe -m py_compile Speak-EPUB-1.0.0/core/config.py` -- 0 exit, `handle_rpc` importable
- `Speak-EPUB-1.0.0/venv/Scripts/python.exe -c "from core.config import handle_rpc; print(handle_rpc({'id':'1','method':'search','params':{'title':'Lord'}}))"` -- `{'id':'1','result':[...]}` mock
- `npm test -- src/components/FindInput.test.tsx -v` -- debounce, skeleton, no-results, keyboard — pass
- `Speak-EPUB-1.0.0/venv/Scripts/python.exe -m lint_imports` -- KEPT (z wyjątkiem `core.config→adapters` udok.)

**Manual checks (if no CLI):**
- Title → skeleton 3, tabela `muted`/`#EFF3FF` left border, `Enter` wybiera; puste → `Brak wyników`+CTA; URL → single row.

## Suggested Review Order

**Contract — Port & validation (entry point)**

- Walidacja strip+truncate przed `search_all` — zapobiega wysyłce 350→200 bez spacji
  [`config.py:150`](../../Speak-EPUB-1.0.0/core/config.py#L150)

- Host-suffix guard `==`/`endswith` zamiast `in` — blokuje spoof `evilnovelphoenix.com`
  [`config.py:284`](../../Speak-EPUB-1.0.0/core/config.py#L284)

- Guard `None` dla `search_all` zwracającego `None` — zapobiega `TypeError` w serializacji
  [`config.py:176`](../../Speak-EPUB-1.0.0/core/config.py#L176)

**Hook — debounced aggregator**

- `guessSiteForUrl` usunięte `includes` — tylko exact/suffix
  [`useDebouncedSearch.ts:24`](../../src/hooks/useDebouncedSearch.ts#L24)

- `buildMockUrlResult` podwójny try/catch dla `%ZZ` — nie połyka całego URL
  [`useDebouncedSearch.ts:42`](../../src/hooks/useDebouncedSearch.ts#L42)

- `searchPromise.catch(()=>{})` przed `Promise.race` — brak unhandled rejection po timeout
  [`useDebouncedSearch.ts:172`](../../src/hooks/useDebouncedSearch.ts#L172)

- `debouncedQuery ?? ""` guard przed `trim()` — chroni SSR/null
  [`useDebouncedSearch.ts:94`](../../src/hooks/useDebouncedSearch.ts#L94)

**UI — FindInput & ResultsTable**

- `navigator` guard `typeof navigator` — brak crash w jsdom/SSR
  [`FindInput.tsx:19`](../../src/components/FindInput.tsx#L19)

- `value?.length` guard — null/undefined nie rzuca
  [`FindInput.tsx:43`](../../src/components/FindInput.tsx#L43)

- `ResultsTable` `null` zamiast hidden `<div>` — nie zostawia węzła w a11y tree
  [`ResultsTable.tsx:53`](../../src/components/ResultsTable.tsx#L53)

- `onSelect` guard `r?.url` + key fallback `r.link` — puste `url` nie psuje selekcji
  [`ResultsTable.tsx:48`](../../src/components/ResultsTable.tsx#L48)

**App wiring & a11y**

- CTA focus guard `if (error) return` — error toast nie kradnie focusa
  [`App.tsx:32`](../../src/App.tsx#L32)

- Reset `selectedUrl` gdy wynik znika — zapobiega stale selection po nowym `query`
  [`App.tsx:40`](../../src/App.tsx#L40)

- Skeleton `aria-busy` + `aria-live` — pozostaje zgodny z spec matrix
  [`App.tsx:135`](../../src/App.tsx#L135)

**Contracts & verification**

- `.importlinter` dynamic `importlib` exception udokumentowany — `core→adapters` static check przechodzi
  [`.importlinter:12`](../../.importlinter#L12)

- `vitest` w `devDependencies` nie `dependencies` — nie puchnie bundle Tauri
  [`package.json:34`](../../package.json#L34)

- `FindInput.test.tsx` Harness skeleton/no-results/Enter — pokrywa debounce + `aria-busy` + roving
  [`FindInput.test.tsx:55`](../../src/components/FindInput.test.tsx#L55)

