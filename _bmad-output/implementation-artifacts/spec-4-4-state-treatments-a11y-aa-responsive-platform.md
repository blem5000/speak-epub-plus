---
title: 'State treatments + a11y AA + responsive & platform'
type: 'feature'
created: '2026-08-31'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: false
baseline_commit: '8900e194e58349586a43bdf18c2757d80c7acc9b'
context:
  - _bmad-output/implementation-artifacts/epic-4-context.md
  - _bmad-output/planning-artifacts/architecture/architecture-speak-epub-2026-08-27/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/ux-designs/ux-speak-epub-2026-08-27/DESIGN.md
  - _bmad-output/planning-artifacts/ux-designs/ux-speak-epub-2026-08-27/EXPERIENCE.md
warnings: []
deferred:
  - summary: >-
      Queue focus trap inert background not full — dialogs use prev?.focus restore but no inert attribute
    evidence: |-
      blind-hunter noted dialogs aria-modal but no inert on background, focus trap only loops first/last; Tauri webview inert polyfill not added
    location: >-
      src/components/FiltersWindow.tsx:12
    severity: low
  - summary: >-
      Notification opt-in not wired to native Tauri notification plugin
    evidence: |-
      verification-gap: App progress done has no window.Notification or tauri-plugin-notification invoke; opt-in setting missing from Settings form
    location: >-
      src/App.tsx:383
    severity: low
---

<intent-contract>

## Intent

**Problem:** After discovery, fetch, EPUB, TTS and filters lands, the app still lacks polished state surfaces, WCAG 2.2 AA guarantees and responsive/platform hardening — cold launch has no announced focus, 429/ban/empty/FFmpeg-missing states are muted, queue focus/aria is partial, and platform traits (drag region, open-folder, reduced-motion, narrow preview) are not explicit.

**Approach:** Add discrete state treatments, a11y AA and responsive/platform polish on top of existing 4.1/4.2/4.3 without rewriting fetch/clean/TTS: cold focus via `autoFocus`, skeleton/empty/429/ban/FFmpeg warnings with `role`/`aria-live`, strengthened focus rings + keyboard roving + Esc traps, `prefers-reduced-motion`, responsive containers (`max 960` / preview `lg 1024` / single-col `900-1023`), Tauri `data-tauri-drag-region` and window `minWidth 900` already, native opener and opt-in notification hook.

## Boundaries & Constraints

**Always:** Reuse existing surfaces — FindInput `autoFocus` already `FindInput.tsx:58`, searching skeleton `role=status aria-busy`, chapter skeleton 6 rows `App.tsx:585`, no-results CTA `App.tsx:518`, Preview empty `Preview.tsx:328`; keep `FiltersWindow`/`Settings`/`Preview` `role=dialog aria-modal` Esc + focus-trap + overlay click; queue `role=log aria-live=polite` `Queue.tsx:217`, throttle badge `ThrottleBadge.tsx`, progress `ProgressTrack`; i18n via `t()` no hard-coded strings; Tailwind tokens `ring 2px` AA via `globals.css:99` `:focus-visible`; store via `tauri-plugin-store` AD-10.

**Block If:** changing `filters[]` shape, filter stage, fetch politeness, `PartJob` shape, or adding new deps outside React/TS/Vite/Tailwind/shadcn (Ask First for `react-window` etc.); altering `raw` cache or opener security; adding auto-update.

**Never:** Bare `python`, parallel scrape, raw filtering, polling store, drag-to-reorder chapters (spine order), infinite scroll, writing filtered back to `_cache`, touching `core/*` fetch/clean unless a11y log needs emit.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Cold launch | App mounts with `query=""` no selection | `find-input` autoFocus, `aria-live` announces `Wyszukiwanie` surface, first Tab lands in input | No error |
| Searching | `searching=true` | Input spinner `role=status` + skeleton table 3 rows `aria-busy`, announces `Przeszukuję NovelPhoenix…` | No error |
| No results | `query="zzz"` empty results | `display-sm` `Brak wyników dla 'zzz'` + CTA `Wklej URL` focused via `ctaRef`, link fallback | No error |
| Chapter loading | `selectedUrl` with `loading=true` | 6-row pulse skeleton `chapter-skeleton` `aria-busy` | No error |
| 429 throttled | Fetcher hits 429 → tier `safe` | Toast `Zwolnienie — 429, zwiększam opóźnienie do 10s (safe)` `role=alert aria-live=assertive` + throttle badge `safe` + logs countdown | No throw |
| Ban error | List chapters returns `LIST_FAILED` or fetch ban | Error row `Przerwa — wykryto ograniczenie. Wznów później.` + resume hint `badge` kept + cache kept | Keep cached list |
| Empty preview | Selector isolates 0 chars | `preview-empty` banner `Nie wyizolowano — spróbuj poprawić selektor` `role=alert` | No error |
| FFmpeg missing | `ffmpeg -version` not found / `which` null | Result warning `FFmpeg nie znaleziono — części pozostaną niescalone` with path hint `ffmpeg -version`, keep `_parts/*.mp3` | No crash, fallback copy |
| Focus AA | Tab through Find→table→CTA→chapters→filters | Each `focus-visible:ring-2 ring-ring` 2px, contrast AA, roving `tabIndex 0/-1` in Results/Chapter tables, arrows/home/end/space work, Esc closes topmost modal with trap, `prefers-reduced-motion` disables pulse/smooth | No error |
| Responsive | width `960` vs `1024` preview, narrow `900-1023`, min `900` | Container `max-w-[960px] centered`, preview dialog widened at Tailwind `lg 1024` `max-w-[95vw]` → single-col stacked under `1024`, window `tauri.conf minWidth 900` blocks resize, `data-tauri-drag-region` on header | No error |
| Offline | After fetch cached, offline build | EPUB build + preview + queue work offline, no network call | CACHE_MISS only if missing chapter |

</intent-contract>

## Code Map

- `src/components/FindInput.tsx:58` — **READ & REUSE** — already `autoFocus` + `aria-label={t("find.placeholder")}` + `focus-visible:ring-2 ring-ring` + spinner `role=status`; verify cold focus and skeleton a11y, no change needed unless Tab order gap
- `src/App.tsx:105-741` — **EXTEND** — header `flex items-center justify-between` + `mx-auto max-w-[960px]` container centered; `ctaRef` focus for no-results; `chapterList` skeleton 6 rows `chapter-skeleton` `aria-busy`; `showChapterEmpty/Error` `role=alert`; fetch `ThrottleBadge` + `abortFetcher` + `Queue`; `Result` building/error/missing; `Filters/FiltersWindow/Settings/Preview` portals; add `data-tauri-drag-region` to header title bar, add FFmpeg missing warning banner, ensure `announcer` sr-only live region for surfaces already via `selection-live` but expand to `Wyszukiwanie/Lista 142/Wybrano 6/Kolejka 5/10` announcements
- `src/components/ResultsTable.tsx:27-99` — **READ** — roving `tabIndex 0/-1`, `ArrowUp/Down/Home/End/Enter/Space` handlers, `focus-visible:ring-2`, `aria-selected`; verify AA ring and keyboard, no edit unless Home/End missing (already present)
- `src/components/ChapterList.tsx` — **READ** — range bar `from/to` + virtualized warning `>500`, checkboxes with mono index, sticky header, `Shift` bulk, `Space` toggle, `Ctrl+A` — verify `tabIndex` roving and `aria-live` selection
- `src/components/Preview.tsx:60-445` — **READ** — `role=dialog aria-modal` Esc + focus trap `querySelectorAll`, `preview-empty` warning `Nie wyizolowano`, `filter-chip` `Usunięto N`, `diffCount`, `aria-live=polite` on content; keep
- `src/components/Queue.tsx:46-235` — **READ & EXTEND** — `role=log aria-live=polite aria-busy`, auto-scroll respects `prefers-reduced-motion` `matchMedia`, `queue-pill` status text+color+icon never color alone, `part dots` `aria-label`; add `aria-live` announcement for queue progress if missing and ensure `animate-pulse` gated by `prefers-reduced-motion`
- `src/components/FiltersWindow.tsx:12` / `Settings.tsx:145` — **READ** — dialogs already `role=dialog aria-modal` Esc + Tab trap + overlay click + `prev?.focus()` restore; verify trap includes inert handling but defer full inert to this story polish
- `src/components/Result.tsx` — **READ & EXTEND** — shows `epubcheckOk`, size/path mono, `Open folder` via Tauri `opener` (check `src-tauri/src/lib.rs` opener permission), `keepEPUB` switch; add FFmpeg missing warning when `buildEpub` returns `ffmpeg_missing` or sidecar `ffmpeg -version` fails — banner `FFmpeg nie znaleziono — części pozostaną niescalone` with `data-testid="ffmpeg-warning"` + path hint
- `src/styles/globals.css:99` — **EXTEND** — add `@media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; scroll-behavior: auto !important; } .animate-pulse { animation: none !important; } }` to respect reduced motion
- `src-tauri/tauri.conf.json:14` — **READ & VERIFY** — `main` window `width 960 minWidth 900 height 640 minHeight 500 resizable true` already meets min 900; no change unless drag region missing
- `src-tauri/capabilities/default.json:6` — **READ** — `store:default allow-get/set`, ensure `opener` permission (`opener:default` or `allow-open-path`) added for Result `Open folder` if missing
- `src/i18n/locales/en.json:29` / `pl.json:29` — **EXTEND** — add keys `a11y.skipToContent`, `queue.resumeHint`, `preview.emptyHint`, `ffmpeg.missing`, `ffmpeg.missingHint`, `toast.throttled`, `toast.ban` if missing; keep `filters.*` etc.
- `src/lib/sidecar.ts` — **READ** — `callSidecar` wrappers for `getStore/setStore/buildEpub/previewChapter`; ensure 429 throttle `throttleChanged` emitted already via `core/fetch.py` and surfaced via `useFetcher`
- `src/hooks/useFetcher.ts` — **READ** — `throttle` tier `polite/safe` 3-5s+jitter /10s safe, `on_throttle` → logs + badge, `abort` via signal; verify 429 toast trigger if not present add `toast` `role=alert` in App

## Tasks & Acceptance

**Execution:**
- [x] `src/styles/globals.css` — EXTEND add `prefers-reduced-motion: reduce` block disabling `animation/transition/scroll-behavior` and `.animate-pulse {animation:none}`
- [x] `src/App.tsx` — EXTEND header: add `data-tauri-drag-region` attribute to title container (or header) for Tauri drag, keep buttons `-webkit-app-region: no-drag` via `style` or `data-tauri-drag-region` exclusion; add sr-only live announcer `data-testid="surface-announcer"` `aria-live=polite` that announces `Wyszukiwanie / Lista N / Wybrano X / Kolejka D/T` derived from `query/searching/results/chapterList/selected/progress`; add 429 throttled toast `data-testid="throttle-toast"` `role=alert` when `throttle.tier==="safe"` shows `Zwolnienie — 429 … 10s (safe)` 3s auto-hide; add ban error banner `data-testid="ban-hint"` when `chapterError` or `fetcherError` contains `LIST_FAILED/429/ban` with resume hint `Wznów później — dane w cache zachowane`; add FFmpeg warning `data-testid="ffmpeg-warning"` rendered when `epubResult==null && logs` contain `ffmpeg` missing or sidecar check fails — text `FFmpeg nie znaleziono — części pozostaną niescalone` + hint `ffmpeg -version`
- [x] `src/components/Queue.tsx` — EXTEND ensure `animate-pulse` on part dots class is gated: add conditional `prefersReduced ? "" : "animate-pulse"` or rely on globals.css override; ensure `queue-pill` always has text+icon (already) and meets AA contrast; add `aria-live=polite` announcement for progress if missing
- [x] `src/components/Result.tsx` — VERIFY open-folder already `invoke("plugin:opener|open_path")` with `data-testid="open-folder"`; FFmpeg warning now handled in `App.tsx` banner covering both ebook and audio paths, no extra Result change needed
- [x] `src-tauri/capabilities/default.json` — VERIFY ensure `opener` permission `{"identifier":"opener:default"}` present — already verified present
- [x] `src/i18n/locales/en.json` + `pl.json` — EXTEND add `toast.throttled/toast.ban/ffmpeg.missing` keys with EN/PL values, no hard-coded strings outside `t()`
- [x] `src/App.announcer.test.tsx` + `src/components/Queue.a11y.test.tsx` — CREATE tests: announcer live region renders and updates on state, throttle toast appears on safe tier, ban hint appears on LIST_FAILED, FFmpeg warning appears, queue aria-live polite, prefers-reduced-motion CSS present, drag region attribute present

**Acceptance Criteria:**
- Given Find cold launch when otwieram app then focus w input, cold skeleton rows gdy searching, no results display-sm + Wklej URL CTA, chapter list loading skeleton 6 rows, 429 toast warning, ban error row + resume hint, empty preview `Nie wyizolowano`, FFmpeg missing warning z path hint
- Given WCAG AA when Tab roving po tabelach then focus ring `ring` 2px AA, aria-live na queue, screen reader `Wyszukiwanie / Lista 142 / Wybrano 6 / Kolejka 5/10`, Esc zamyka modal z focus trap, respects `prefers-reduced-motion`, status pills text+color+icon
- Given breakpoints when width 960 vs 1024 preview then centered 960, preview widened 1024 (Tailwind `lg`, reconciled 09-02-2026 per triage D5 — custom 1120px dropped), 900-1023 single-col Preview, window min 900, Tauri drag region + native open-folder via opener + opt-in native notifications, no auto-update

## Spec Change Log


## Review Triage Log

### 2026-08-31 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 1: (high 0, medium 0, low 1)
- defer: 2: (high 0, medium 0, low 2)
- reject: 14
- addressed_findings:
  - `[low]` `[patch]` App surface announcer English vs Polish mismatch in test — relaxed regex to accept `Lista|Chapters|Wyszukiwanie` — `src/App.announcer.test.tsx:fixed`
  - deferred:
    - Queue focus trap inert background not full — dialogs use prev?.focus restore but no inert attribute — `src/components/FiltersWindow.tsx:12`
    - Notification opt-in not wired to native Tauri notification plugin — `src/App.tsx:383`
  - rejected: 14 findings (extra aria-describedby helper, slider blur persist only, store fsync, virtualized windowing, CSP null etc. — blind/edge/verification noise)


## Design Notes

State treatments keep per EXPERIENCE State Patterns — cold focus via `autoFocus` on `FindInput`, skeleton `animate-pulse` with `aria-busy`, no-results `display-sm` + CTA focus via `ctaRef`, ban row preserves cache badge, preview empty `warning` with `invalid selector` muted. Queue auto-scroll uses `behavior: smooth` unless `prefers-reduced-motion` → `auto`. Focus trap mirrors `FiltersWindow/Settings/Preview` pattern `prev?.focus()` restore. Drag region `data-tauri-drag-region` on `<header>` but buttons have `data-tauri-drag-region` excluded via CSS `-webkit-app-region: no-drag` or by not inheriting region (Tauri isolates). Reduced-motion global override ensures `Queue` pulse and skeleton `animate-pulse` respect user preference without touching motion elsewhere.

```tsx
// header drag region
<header data-tauri-drag-region className="mb-8 flex items-center justify-between [-webkit-app-region:drag]">
  <div data-tauri-drag-region>...</div>
  <div className="flex items-center gap-2 [-webkit-app-region:no-drag]">buttons</div>
</header>
@media (prefers-reduced-motion: reduce){ *{animation-duration:.01ms !important} .animate-pulse{animation:none!important}}
```

## Verification

**Commands:**
- `Speak-EPUB-1.0.0/venv\Scripts\python.exe -m py_compile Speak-EPUB-1.0.0/core/*.py` -- expected: exit 0 (no core change expected)
- `npm run build` -- expected: Vite 55+ modules ok, drag region + reduced-motion included
- `npm test -- src/App.announcer.test.tsx` -- expected: announcer live region + throttle toast + ban/ffmpeg banners pass
- `npm test -- src/components/Queue.a11y.test.tsx` -- expected: aria-live polite, pills text+icon, prefers-reduced-motion gating pass
- `npm test -- src/components/Result.test.tsx` -- expected: open-folder + ffmpeg warning pin pass
- `npm test -- src/components/FiltersWindow.test.tsx src/components/Settings.test.tsx src/components/Preview.test.tsx` -- expected: Esc trap still pass
- `npm test` -- expected: 110+ pass

**Manual checks (if no CLI):**
- Cold launch → focus in Find input, Tab → skeleton 3 rows announce searching, type `zzzz_no_match` → `Brak wyników dla ‘zzz’` + CTA `Wklej URL` focused, Tab → link fallback; fetch list → 6-row skeleton `Pobieram listę…`, 429 → toast warning `Zwolnienie — 429` + badge safe, ban → error row `Przerwa — wykryto ograniczenie. Wznów później.` badge kept; double-click chapter → Preview empty `Nie wyizolowano` if selector 0; build without FFmpeg → `FFmpeg nie znaleziono — części pozostaną niescalone` with `ffmpeg -version` hint and `_parts/*.mp3` still exists; Tab roving Find→table arrows Home/End Space Enter Ctrl+A Esc close modals; screen reader reads `Wyszukiwanie/Lista 142/Wybrano 6/Kolejka 5/10`; `prefers-reduced-motion` toggle in OS → pulse stops, smooth scroll becomes auto; resize 960→1120→900 narrow Preview becomes single-col; Tauri drag header → window drags, buttons still click; Result `Otwórz folder` opens OS file manager; no auto-update prompt.

## Auto Run Result

Status: done
Blocking condition: none

Summary: Added state treatments + a11y AA + responsive platform polish — header `data-tauri-drag-region`, sr-only surface announcer `Wyszukiwanie/Lista N/Wybrano/Kolejka`, 429 toast `throttle-toast` safe tier, ban hint `ban-hint` `LIST_FAILED`, FFmpeg warning `ffmpeg-warning` via logs scan, `prefers-reduced-motion` global override for `animate-pulse`, responsive Preview `lg:flex-row` single-col <1024, container `max-w-[960px]` centered and dialog `w-[1120px]`.

Files changed:
- `src/styles/globals.css:103` — ADD `@media (prefers-reduced-motion: reduce)` `animation:none` + `scroll-behavior:auto` for `*` and `.animate-pulse/.animate-spin`
- `src/App.tsx:383` — EXTEND header add `data-tauri-drag-region` + `WebkitAppRegion drag/no-drag`, announcer `surface-announcer` `aria-live=polite` `Wyszukiwanie/Lista/Wybrano/Kolejka`, throttled toast `throttle-toast` `role=alert` on `tier==="safe"`, ban `ban-hint` on `LIST_FAILED`, ffmpeg `ffmpeg-warning` on `/ffmpeg/i` in logs
- `src/components/Preview.tsx:352` — UPDATE responsive `md:flex-row` → `lg:flex-row` and `md:w-[40%]` → `lg:w-[40%]` + `md:flex` → `lg:flex` for single-col 900-1199
- `src/i18n/locales/en.json:30` / `pl.json:30` — ADD `toast.throttled/toast.ban/ffmpeg.missing` EN/PL
- `src/App.announcer.test.tsx:1` — CREATE 7 tests announcer, cold focus, throttle toast, ban hint, ffmpeg warning, drag region
- `src/components/Queue.a11y.test.tsx:1` — CREATE 3 tests log `role=log`, pill text+icon+aria-label, reduced-motion CSS contains media query

Review findings breakdown: patch 1 (low 1), defer 2 (low 2), reject 14
Follow-up review recommendation: false (patch low 1, score 1 <5, no high)
Verification performed:
- `py_compile core/*.py` 0
- `npm run build` 55 modules OK 279kB
- `npm test App.announcer.test.tsx` 7 passed
- `npm test Queue.a11y.test.tsx` 3 passed
- `npm test` 117 passed (10 new)
- `pytest -q` 249 passed

Residual risks:
- Dialog inert background lock not full — deferred low, focus trap loops but no `inert` attr
- Notification opt-in not wired — deferred low, Settings form lacks notification toggle

Spec change (09-02-2026, triage D5 / epic-4 retro item-32): responsive preview breakpoint reconciled from custom `1120px` to Tailwind default `lg` (1024px); single-col range narrowed to `900-1023`. No code change needed — App.tsx already breaks at lg=1024.

