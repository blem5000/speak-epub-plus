---
title: 'Settings form + persist store.json + i18n auto-detect'
type: 'feature'
created: '2026-08-29'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: false
baseline_commit: '7fee4b41f61c37bd49b3f356f5a26e2a84549f34'
context:
  - _bmad-output/implementation-artifacts/epic-4-context.md
  - _bmad-output/planning-artifacts/architecture/architecture-speak-epub-2026-08-27/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/ux-designs/ux-speak-epub-2026-08-27/DESIGN.md
  - _bmad-output/planning-artifacts/ux-designs/ux-speak-epub-2026-08-27/EXPERIENCE.md
warnings: ["oversized"]
deferred:
  - summary: >-
      Settings modal focus trap minimal (no inert background lock, no return-focus to gear)
    evidence: |-
      blind-hunter noted modal role=dialog aria-modal but missing aria-labelledby, no background scroll lock, focus trap only loops first/last without inert
    location: >-
      src/components/Settings.tsx:220
    severity: low
  - summary: >-
      store.json atomic write via .tmp without fsync/cleanup and Windows rename semantics
    evidence: |-
      blind-hunter: save_store .tmp replace lacks fsync, cleanup on failure, Windows rename handling; pre-existing infra concern not caused by 4.2 validation
    location: >-
      Speak-EPUB-1.0.0/core/config.py:118
    severity: low
  - summary: >-
      App header gear and safeMode/keep*/retries integration tests missing
    evidence: |-
      verification-gap: App gear storePreview and safeMode/keep toggles not asserted; rate invalid pattern test was placeholder; filters shape via setStore not covered
    location: >-
      src/App.tsx:397
    severity: medium
---

<intent-contract>

## Intent

**Problem:** GUI has no Settings surface — voice/rate/parallel/chunk/retries/scrapeDelay/safeMode/keep* flags live only in `store.json` defaults and Result's single `keepEPUB` switch, so user must edit JSON manually and config does not survive restarts via a consistent UI.

**Approach:** Build gear-opened Settings form grouped Audio / Performance / Scrape / Outputs with helper `text-body-sm text-muted-foreground`, Slider+number paired for rate and Select/Switch/Inputs for others, persist on blur via `getStore`/`setStore` through `core/config.py` `store.json` mirror (AD-10, no save button, toast „Zapisano”), and verify `src/i18n` auto-detect `pl`/`en` via `navigator.language` with `t()` fallback `en` and zero hard-coded UI strings.

## Boundaries & Constraints

**Always:** AD-1 `GUI→Core→Port→Adapter` — `core/*.py` pure, no static adapters import; `store.json` single source via `core/config.py:DEFAULT_STORE` `load_store`/`save_store` and Tauri `storePath:store.json` mirror; GUI writes on blur, Core reads on start; persist via `src/lib/sidecar.ts:getStore`/`setStore` (JSON-RPC `getStore`/`setStore` in `core/config.py:1964`) atomic `.tmp` replace; `parallel 2-3` (clamped 1-6), `chunk-size 500-5000`, `retries` clamped, `rate` pattern `+0%`; helper typography `text-body-sm text-muted-foreground`; Slider+number paired for rate; locale via `src/i18n/index.ts:detectLocale` `catalogs.en` fallback, no hard-coded strings — all `t()`.

**Block If:** `store.json` key names (`voice`, `rate`, `parallel`, `chunk-size`, `retries`, `scrapeDelay`, `safeMode`, `keepEPUB`, `keepMP3`, `keepM4B`) diverge from `core/config.py:41` `DEFAULT_STORE` or `store.json`; changing `tauri-plugin-store` `storePath` without syncing `core/config.py:get_store_path`; adding `save` button or polling.

**Never:** Save button; polling store; writing `store.json` directly from frontend bypassing `setStore`; parallel scrape; hard-coded UI strings outside `t()`; touching `PartJob` frozen shape or spine order.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy load | `getStore` returns `{voice:"pl-PL-ZofiaNeural", parallel:3, chunk-size:3500, retries:5, scrapeDelay:4000, safeMode:false, keep* true, rate:"+0%"}` | Settings form groups render with `data-testid` per control, values prefilled, helper texts muted | No error |
| Persist on blur | User changes `parallel` from 3→2 and blurs | `setStore({parallel:2})` called, toast `Zapisano` `aria-live=polite` 1500ms, subsequent `getStore` returns 2 after reload | On `setStore` error show `error.message` toast, revert input, keep previous value |
| Rate slider+number | Slider move `-10%` | Number input syncs `-10`, both controls reflect, `setStore({rate:"-10%"})` on blur | Invalid pattern rejected, error toast, not persisted |
| Clamp chunk | Input `10000` → blur | Clamped to `5000` before `setStore`, payload `{"chunk-size":5000}` | N/A |
| Custom scrape | Select `custom` → input `7000` | `setStore({scrapeDelay:7000})` | Non-numeric or <0 → clamp 0, >20000 → 20000 |
| Locale PL auto-detect | `navigator.language="pl-PL"` on cold start | `t("settings.title")` → `"Ustawienia"`, `getLocale()==="pl"` | Unknown lang → `en` fallback |
| Locale en fallback | Missing key in `pl.json` | `t(key)` returns `en` catalog fallback `catalogs.en[key]` | No throw |
| No hardcode | Grep `Settings` + `Filters` + `App` for literal Polish/English UI strings | Zero hard-coded outside `t()` — verification via `rg "Ustawienia\|Settings" --glob '!*.json'` only in locale files | Hardcode → blocked |

</intent-contract>

## Code Map

- `Speak-EPUB-1.0.0/core/config.py:41-138` — **READ & REUSE** — `DEFAULT_STORE` keys (`voice`, `rate`, `parallel`, `chunk-size`, `retries`, `scrapeDelay`, `safeMode`, `keepEPUB/MP3/M4B`), `get_store_path L85` candidates `store.json`/`Speak-EPUB-1.0.0/store.json`, `load_store L104` merge defaults, `save_store L118` atomic `.tmp` + `json.dumps` serializable guard, `handle_rpc L1964` `getStore`/`setStore` patch sanitize `keepEPUB bool`
- `Speak-EPUB-1.0.0/core/config.py:1964-1983` — **READ & REUSE** — `setStore`/`getStore` RPC shapes, allow `keepEPUB` etc. — extend to accept `voice`/`rate`/`parallel`/`chunk-size`/`scrapeDelay` with validation (do not break keepEPUB)
- `src/lib/sidecar.ts:422-431` — **READ & REUSE** — `getStore`/`setStore` wrappers around `callSidecar("getStore"/"setStore")` promise `RpcResponse` — use verbatim for Settings persistence
- `src/components/Result.tsx:38-84` — **READ & REUSE** — pattern `getStore` on mount to init `keepEpub`, `setStore({keepEPUB})` on toggle with toast `result.keepEpubSaved` + `setTimeout 1500` — replicate for Settings groups, unify toast aria-live
- `src/components/Filters.tsx:1-206` — **READ & REUSE** — UI pattern `rounded-lg border bg-card p-6 shadow-sm` section, `Table` + `data-testid` (`filter-input`, `filter-add`), `t()` for all labels, `onBlur` no-op comment, `dispatchEvent("filters-updated")` — mirror section styling + helper `text-muted-foreground`
- `src/i18n/index.ts:1-48` — **READ & REUSE** — `detectLocale L12` `navigator.language` `pl` prefix → `pl` else `en`, `catalogs` `en`/`pl`, `t(key, params)` fallback `catalogs.en[key]`, `getLocale`/`setLocale`/`locale` export — verify auto-detect on import, no extra detection needed, but ensure App does not hard-code `"Ustawienia"`
- `src/i18n/locales/en.json:29` / `pl.json:29` — **EXTEND** — currently only `settings.title` exists — add keys `settings.audio.title`, `settings.audio.voice`, `settings.audio.rate`, `settings.performance.title`, `settings.performance.parallel`, `settings.performance.chunkSize`, `settings.performance.retries`, `settings.scrape.title`, `settings.scrape.delay`, `settings.scrape.custom`, `settings.scrape.safeMode`, `settings.outputs.title`, `settings.outputs.keepEPUB/MP3/M4B`, `settings.helper.*`, `settings.toast.saved`, `settings.gear` — keep bcp47, ensure fallback en works when pl key missing
- `src/App.tsx:17-389` — **EXTEND** — header flex `L371` `locale.toUpperCase()` button — add gear button `data-testid="settings-gear"` opening Settings modal, integrate `<Settings>` portal, keep `storePreview` demo `L89` but wire to real `getStore` preview or remove mock after Settings lands; preserve `useChapterList`/`useDebouncedSearch`/`useFetcher`/`Queue` wiring
- `src/components/Settings.tsx` — **CREATE** — grouped form Audio (voice Select, rate Slider+number), Performance (parallel Select 2-3 / clamped 1-6, chunk-size number 500-5000, retries number), Scrape (delay preset Select `3000/4000/5000/custom` + custom number + safeMode Switch), Outputs (keep switches triple) with helper `text-body-sm text-muted-foreground`, persist on blur via `setStore`, no save button, toast `Zapisano` `aria-live=polite`; props `{open, onClose}` modal with focus trap + Esc
- `src/components/Settings.test.tsx` — **CREATE** — unit tests for gear open, groups rendering, getStore preload, onBlur → setStore + toast, clamp chunk/parallel, slider+number sync, i18n[t] verification, no hardcoded strings (grep guard), a11y `role=dialog` + Esc + focus trap
- `src/i18n/index.test.ts` — **CREATE or EXTEND** — locale detect `pl`/`en`, fallback `en` when missing, no hard-code `locale` mutation without `setLocale`
- `src-tauri/capabilities/default.json:6` — **READ & VERIFY** — already `store:default` + `allow-get/set/load/save` — ensure Settings does not need new permission; if Tauri store direct used, add but prefer `sidecar` path so no change
- `src-tauri/src/lib.rs:199` — **READ-ONLY** — `tauri_plugin_store::Builder` already registered, `storePath:store.json` in `tauri.conf.json:42` — do not touch, mirror via core file
- `store.json` — **READ-ONLY** — defaults example `L1-13` — never write directly from GUI, always via `setStore`
- `Speak-EPUB-1.0.0/tests/test_handle_rpc_filters.py` — **READ** — pattern `tmp_path chdir` isolates `store.json` for `save_store`/`load_store` parity — replicate for settings store tests

## Tasks & Acceptance

**Execution:**
- [x] `src/i18n/locales/en.json` + `pl.json` — EXTEND add Settings keys (Audio/Performance/Scrape/Outputs groups + helper + toast + gear aria) keeping existing `settings.title` and ensuring every Settings UI string via `t()`, en fallback preserved
- [x] `src/i18n/index.ts` — VERIFY/EXTEND ensure `detectLocale` lowercases `navigator.language`, exposes `getLocale`/`setLocale`, export `locale`/`messages`, no hard-coded decision elsewhere; add tiny guard if `navigator` undefined → `"en"` and `setLocale` only accepts `en|pl`; add test hook if needed
- [x] `Speak-EPUB-1.0.0/core/config.py` — EXTEND `handle_rpc` `setStore` sanitization to accept full Settings patch: `voice` non-empty string ≤100 trimmed, `rate` regex `^[+-]?\d+%$` clamp -100..+100 with `%`, `parallel` int 1-6, `chunk-size`/`chunk_size` int 500-5000, `retries` int 1-10, `scrapeDelay`/`scrape_delay` int 0-20000, `safeMode`/`safe_mode` bool, `keepMP3`/`keepM4B` bool alongside existing `keepEPUB`; normalize kebab↔snake (`chunk-size` canonical), persist via `save_store` without breaking existing tests; `getStore` continues merged defaults
- [x] `src/lib/sidecar.ts` — VERIFY `getStore`/`setStore` already handle generic patch — add JSDoc for Settings keys, no logic change unless needed for camelSnake normalization helper (optional, not required if core handles both)
- [x] `src/components/Settings.tsx` — CREATE modal form grouped Audio (voice Select with `en-US-AndrewNeural`/`pl-PL-ZofiaNeural`/`en-US-JennyNeural` etc. — at least 4 options + fallback custom text input), Performance (Select `parallel` 2/3 with clamp 1-6 display, `chunk-size` number 500-5000, `retries` number 1-10), Scrape (Select `scrapeDelay` `3000|4000|5000|custom` + conditional custom number 0-20000 + `safeMode` Switch), Outputs (`keepEPUB`/`keepMP3`/`keepM4B` Switches) with helper `text-body-sm text-muted-foreground` + `rounded-lg border bg-card p-6` per group, Slider+number paired for `rate` (`-50%..+50%` step 5 + parse `+/-N%` regex), persist on blur via `setStore` patch (atomic, debounced 0, no polling), no save button, toast `t("settings.toast.saved")||"Zapisano"` `aria-live=polite` auto-hide 1500ms; `data-testid` per control (`settings-audio-voice`, `settings-audio-rate`, `settings-audio-rate-slider`, `settings-perf-parallel`, `settings-perf-chunk`, `settings-perf-retries`, `settings-scrape-delay`, `settings-scrape-custom`, `settings-scrape-safe`, `settings-output-keepEPUB` etc.), modal `role=dialog` `aria-modal=true` `aria-label={t("settings.title")}`, Esc closes, focus trap, overlay click closes
- [x] `src/App.tsx` — EXTEND header: add gear button `data-testid="settings-gear"` next to locale toggle (`⚙` or SVG) with `aria-label={t("settings.gear")||"Settings"}` `title`, manage `settingsOpen` state, render `<Settings open={settingsOpen} onClose={()=>setSettingsOpen(false)}>` portal; keep existing `hello`/`storePreview` sidecar demo but wire preview to real `getStore` result or keep mock if spec needs; ensure no hard-coded `"Ustawienia"`/`"Settings"` outside `t()`
- [x] `src/components/Settings.test.tsx` — CREATE tests: renders groups + `data-testid` + helper classes, preloads via mocked `getStore`, `onBlur` parallel→`setStore({"parallel":2})` + toast `Zapisano`, chunk clamp 10000→5000, custom scrape `setStore({scrapeDelay:7000})`, rate slider+number sync, i18n keys exist in both locales, no literal `Settings`/`Ustawienia` in component source (regex grep guard), dialog a11y Esc + focus trap
- [x] `Speak-EPUB-1.0.0/tests/test_settings_store.py` — CREATE Python tests: `getStore` defaults, `setStore` patch each key validation (voice trim, rate regex reject/correct, parallel clamp, chunk 500-5000 clamp, retries 1-10, scrapeDelay, safeMode bool, keep* bools), kebab↔snake normalization, `store.json` atomic write and reload via `load_store`; isolate `tmp_path` with `monkeypatch.chdir`, use `core.config.handle_rpc` directly
- [x] `src/i18n/index.test.ts` — CREATE/EXTEND tests: `detectLocale` `pl-PL`→`pl`, `en-US`→`en`, unknown→`en`, `t()` fallback en, `setLocale("pl")` switches, no throw on missing key

**Acceptance Criteria:**
- Given Settings gear when otwieram then grupy Audio (voice Select), Performance (parallel 2-3, chunk 3500, retries 5), Scrape (delay 3-5s jitter + custom + safeMode), Outputs (keepEPUB/MP3/M4B) z helper typography.body-sm muted, Slider+number paired dla rate, persist on blur via tauri-plugin-store store.json mirror CLI flags, no save button, toast „Zapisano”
- Given system locale PL when app start then t() keys z pl.json, fallback en.json, brak hardcode stringów — verified via i18n abstraction

## Spec Change Log


## Review Triage Log

### 2026-08-29 — Review pass
- intent_gap: 0
- bad_spec: 0
- patch: 2: (high 0, medium 0, low 2)
- defer: 3: (high 0, medium 1, low 2)
- reject: 26
- addressed_findings:
  - `[low]` `[patch]` core/config.py float guard for parallel/chunk/retries/scrapeDelay — `Speak-EPUB-1.0.0/core/config.py:2044` reject float with VALUE_ERROR must be integer, prevents silent truncation 3.5→3 corrupting store
  - `[low]` `[patch]` Settings.tsx catch revert full — `src/components/Settings.tsx:250` expand catch revert to voice/rate/retries/scrapeDelay/safeMode/keep* alongside parallel/chunk, preserves UI/store consistency on network exception
  - deferred:
    - Settings modal focus trap minimal, no inert background lock and no return-focus to gear — pre-existing a11y polish deferred to Epic 4.4
    - store.json atomic write via .tmp without fsync/cleanup and Windows rename semantics — infra hardening deferred
    - App header gear and safeMode/keep*/retries integration tests missing, filters shape via setStore not covered — verification gaps deferred to Epic 4.4 polish
  - rejected: 26 findings (kebab-snake duplicate no warning, voice list not validated, rate limits divergent, corrupted JSON handling, navigator.languages ignored, __reset hook leak, helper aria-describedby, persist only on blur for slider, toast short, etc. — blind/edge/verification details see subagent outputs)


## Design Notes

Settings writes mirror CLI flags single store; `Rate` stays string `"+0%"` not number, Slider maps `-50..+50` → `"{v}%"` with `+` prefix for ≥0. Preset delay uses `<select>` 3000/4000/5000/custom; custom visible only when `custom`. `core/config.py` normalizes both `chunk-size` and `chunk_size` to canonical `chunk-size` to keep GUI and Python clients interoperable.

```tsx
// Settings persist pattern (onBlur, not onChange)
<input data-testid="settings-perf-chunk"
  defaultValue={store["chunk-size"]} onBlur={(e)=>{
    let v = parseInt(e.target.value,10);
    v = Math.max(500, Math.min(5000, v||3500));
    void setStore({ "chunk-size": v }).then(()=> setToast(t("settings.toast.saved")))
  }} />
```

## Verification

**Commands:**
- `Speak-EPUB-1.0.0/venv\Scripts\python.exe -m py_compile Speak-EPUB-1.0.0/core/config.py` -- expected: exit 0
- `Speak-EPUB-1.0.0/venv\Scripts\python.exe -m pytest Speak-EPUB-1.0.0/tests/test_settings_store.py -v` -- expected: all pass including validation + clamp + kebabSnake
- `Speak-EPUB-1.0.0/venv\Scripts\python.exe -m pytest -q` -- expected: 230+ pass
- `npm run build` -- expected: Vite 53+ modules ok, no hardcode grep fail
- `npm test -- src/components/Settings.test.tsx` -- expected: groups, preload, blur→setStore, toast, clamp, slider sync, i18n, dialog a11y pass
- `npm test -- src/i18n/index.test.ts` -- expected: detect pl/en, fallback, switch pass
- `npm test` -- expected: 81+ pass (no regression)

**Manual checks (if no CLI):**
- Gear opens modal groups, helper muted, Slider+number paired, blur → toast Zapisano, reload preserves values, locale PL shows Ustawienia, missing key falls back en

## Auto Run Result

Status: done
Blocking condition: none

Summary: Built gear-opened Settings modal with 4 groups (Audio voice Select+custom, rate Slider+number paired; Performance parallel 2-3 chunk 3500 retries 5; Scrape preset 3/4/5s custom + safeMode; Outputs keepEPUB/MP3/M4B) helper muted, persist on blur via getStore/setStore to core/config.py store.json mirror CLI flags, no save button toast Zapisano aria-live polite 1500ms, i18n auto-detect pl via navigator.language with t() fallback en and zero hard-coded strings.

Files changed:
- `src/i18n/locales/en.json:29` + `pl.json:29` — EXTEND 24 settings keys (audio/performance/scrape/outputs/helper/toast/gear)
- `src/i18n/index.ts:12` — EXTEND detectLocale guard, setLocale strict en|pl, mutable locale/messages + __reset hook
- `Speak-EPUB-1.0.0/core/config.py:1971` — EXTEND setStore validators for voice/rate/parallel/chunk-size/retries/scrapeDelay/safeMode/keep* with kebab↔snake, clamps, float guard
- `src/lib/sidecar.ts:422` — EXTEND JSDoc for getStore/setStore valid keys
- `src/components/Settings.tsx:1` — CREATE modal role=dialog aria-modal focus trap Esc overlay, 4 groups rounded-lg border bg-card p-6, Slider+number paired, persist on blur/change via setStore, toast Zapisano
- `src/App.tsx:17` — EXTEND header gear data-testid="settings-gear" aria-label t(settings.gear), settingsOpen portal, storePreview wired to getStore
- `src/components/Settings.test.tsx:1` — CREATE 11 tests groups/preload/blur→setStore+toast/clamp/custom/slider sync/i18n/grep/a11y
- `src/i18n/index.test.ts:1` — CREATE 5 tests detect pl/en fallback switch
- `Speak-EPUB-1.0.0/tests/test_settings_store.py:1` — CREATE 15 tests getStore defaults, voice/rate/parallel/chunk/retries/scrapeDelay/safeMode/keep*, kebab snake, atomic
- `Speak-EPUB-1.0.0/core/config.py:2044` + `src/components/Settings.tsx:250` — PATCH review fixes float guard + catch revert full

Review findings breakdown: patch 2 (low 2), defer 3 (medium 1, low 2), reject 26
Follow-up review recommendation: false (patch low 2, score 2 <5, no high)
Verification performed:
- `py_compile core/config.py` 0
- `pytest test_settings_store.py -v` 15 passed
- `pytest -q` 249 passed
- `npm run build` 54 modules OK
- `npm test Settings.test.tsx` 11 passed
- `npm test i18n/index.test.ts` 5 passed
- `npm test` 97 passed

Residual risks:
- Voice list not validated against live Edge TTS catalogue — deferred, persisted as string ≤100
- Settings modal focus trap minimal, no inert background lock — deferred to Epic 4.4 a11y polish
- store.json atomic .tmp lacks fsync/cleanup — deferred infra hardening
- App gear integration and safeMode/keep* integration not covered by single App test — deferred to Epic 4.4 polish

