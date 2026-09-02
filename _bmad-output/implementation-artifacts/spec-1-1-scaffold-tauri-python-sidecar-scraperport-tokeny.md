---
title: 'Scaffold Tauri + Python sidecar + ScraperPort + tokens'
type: 'feature'
created: '2026-08-27'
status: 'done'
baseline_commit: 'eeb9016650b0a16380e3670856b748e2201008e3'
review_loop_iteration: 0
context:
  - _bmad-output/specs/spec-speak-epub/SPEC.md
  - _bmad-output/planning-artifacts/architecture/architecture-speak-epub-2026-08-27/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/ux-designs/ux-speak-epub-2026-08-27/DESIGN.md
  - _bmad-output/implementation-artifacts/epic-1-context.md
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** No runnable desktop shell exists — remaining epics lack a stable `GUI → Core → ScraperPort → Adapter` contract, OS-aware venv resolution, and design-token foundation, so every later story would rewrite scaffolding.
**Approach:** Scaffold Tauri 2.11.5 with React 18/TS5/Vite6/Tailwind4/shadcn via `create-tauri-app 4.7.3`, expose DESIGN.md tokens as CSS vars, create `Speak-EPUB-1.0.0/core/ports.py` ScraperPort ABC + `core/config.py` OS-aware venv path, add `adapters/novelphoenix.py` skeleton, wire `tauri-plugin-shell`/`store` JSON-RPC sidecar spike, and enforce import linter. Discovery surfaces remain mocks in this story.

## Boundaries & Constraints

**Always:** `GUI → Core → Pipeline` and `Core → ScraperPort → Adapter` — adapters never import pipeline/GUI; pipeline never imports concrete adapters (AD-1). Venv path via `core/config.py` OS detection `Speak-EPUB-1.0.0/venv/Scripts/python.exe` Win vs `venv/bin/python` macOS/Linux — never bare `python` (AGENTS.md). Design tokens (colors/typography/rounded/spacing) as CSS vars + Tailwind theme. Single `store.json` via `tauri-plugin-store` mirroring CLI flags (voice/rate/parallel/chunk-size/retries/scrapeDelay/safeMode/keep*/filters). JSON-RPC stdin/stdout primary, HTTP fallback documented, sequential fetch only (no parallel scrape).
**Ask First:** Bumping Tauri/create-tauri-app/plugin versions; adding deps beyond React/Vite/Tailwind/shadcn/edge-tts/ebooklib/bs4/lxml; modifying `speak.py:split_text_for_tts` or `PartJob` frozen shape; changing sidecar transport away from shell.
**Never:** Implement real `search`/`listChapters`/`fetchChapter` network logic (mock only); build full Find/ChapterList UI (1.3/1.4) or Queue/EPUB/TTS pipelines (Epics 2-3); modify `Speak-EPUB-1.0.0/venv`; add polling (single typed event bus only AD-6); touch FFmpeg/M4B logic; introduce env vars/registry for config.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Sidecar spawn | `core/config.py` resolves venv per OS, Tauri shell spawns | `store.json` loads, `{"type":"hello"}` round-trips over stdin/stdout in <2s | If spawn fails, log `sidecar failed: <venvPath>` + fallback to `http://localhost:17381` doc path, app stays open with warning toast |
| Import linter | `core/ports.py` defines ABC, adapter imports it | `lint:imports` passes | `core → adapters.*` or `adapters → core.pipeline` → fail CI with file:line pointing |
| Tokens injection | `DESIGN.md` tokens injected as CSS vars | `npm run build` includes `var(--color-accent)` `#2B5CE6`, `rounded-md 8px`, `font-mono JetBrains` | Missing token → build fails with token name in error |
| Locale detect | `navigator.language` `pl`/`en` | `t('find.placeholder')` shows correct locale, fallback `en` | Unknown locale → fallback `en.json`, no hard-coded strings |

</frozen-after-approval>

## Code Map

- `Speak-EPUB-1.0.0/speak.py:1-120,140-260` — brownfield invariants: `PartJob` frozen `speak.py:62-69`, `split_text_for_tts(max_chars=3500)`, `extract_chapters` spine-order `<100` skip, global queue parallel 2-3/5 retries — reuse verbatim, reference only
- `Speak-EPUB-1.0.0/requirements.txt` — pin `ebooklib==0.20`, `beautifulsoup4`, `edge-tts==7.2.8`, `lxml==6.0.2`
- `Speak-EPUB-1.0.0/core/ports.py` — **NEW** — `ScraperPort` ABC `search/listChapters/fetchChapter/getSelectors` + frozen DTOs — AD-1 enforcement
- `Speak-EPUB-1.0.0/core/config.py` — **NEW** — `get_venv_python()` OS-aware (`Scripts/python.exe` Win vs `bin/python`), `store.json` path, CLI mirror
- `Speak-EPUB-1.0.0/core/__init__.py` + `adapters/__init__.py` + `adapters/base.py` — **NEW** — package markers, `guess_adapter(url)` fallback
- `Speak-EPUB-1.0.0/adapters/novelphoenix.py` — **NEW** — skeleton `ScraperPort` impl, `NotImplementedError` for network, default selectors — proves direction
- `Speak-EPUB-1.0.0/adapters/overrides/.gitkeep` — **NEW** — per-site selector overlays dir (AD-7)
- `src-tauri/Cargo.toml` + `tauri.conf.json` + `src/main.rs` — **NEW** — Tauri 2.11.5 + `shell 2.x`/`store 2.x`, window 960/min900, sidecar spawn stub
- `package.json` + `vite.config.ts` + `tsconfig.json` + `tailwind.config.ts` — **NEW** — React 18/TS5/Vite6/Tailwind4/shadcn base
- `src/styles/globals.css` + `tokens.ts` — **NEW** — CSS vars from `DESIGN.md` (`#F8F9FA`, `#2B5CE6`, rounded `sm6/md8/lg12/xl16`, mono `JetBrains 12`)
- `src/i18n/index.ts` + `locales/{en,pl}.json` + `src/App.tsx` + `src/main.tsx` — **NEW** — auto-detect `navigator.language`, `t()` helper, 960px shell token demo
- `_bmad-output/planning-artifacts/architecture/architecture-speak-epub-2026-08-27/ARCHITECTURE-SPINE.md:28-110` — AD-1/AD-4/AD-5/AD-6/AD-10 invariants
- `_bmad-output/planning-artifacts/ux-designs/ux-speak-epub-2026-08-27/DESIGN.md:9-85` — token source — distill
- `Run-SpeakEPUB.cmd/ps1` + `.gitignore` — read-only: keep double-click behavior, ensure `venv/` ignored

## Tasks & Acceptance

**Execution:**
- [x] `src-tauri/Cargo.toml` + `src-tauri/tauri.conf.json` + `src-tauri/src/main.rs` — scaffold Tauri 2.11.5 via `create-tauri-app 4.7.3` template, add `tauri-plugin-shell` + `tauri-plugin-store`, window 960px/min 900, bundle per OS — rationale AD-4 sidecar contract
- [x] `package.json` + `vite.config.ts` + `tsconfig.json` + `tailwind.config.ts` + `index.html` + `src/main.tsx` + `src/App.tsx` + `src/lib/utils.ts` — init React 18/TS5/Vite6/Tailwind4/shadcn base, `npm run tauri dev` boots — rationale foundation gate for 1.3/1.4 surfaces
- [x] `src/styles/globals.css` + `src/styles/tokens.ts` — inject DESIGN.md tokens as CSS vars (`--background`, `--ring #2B5CE6`, `--rounded-md 8px` etc.) and Tailwind theme extend, dark pairs — rationale UX-DR1 visual contract
- [x] `src/i18n/index.ts` + `src/i18n/locales/en.json` + `src/i18n/locales/pl.json` — auto-detect `navigator.language` (pl→pl.json, else en), `t()` abstraction, no hardcoded UI strings — rationale AGENTS.md locale + AD-10 string discipline
- [x] `Speak-EPUB-1.0.0/core/__init__.py` + `Speak-EPUB-1.0.0/core/ports.py` + `Speak-EPUB-1.0.0/core/config.py` + `Speak-EPUB-1.0.0/adapters/__init__.py` + `Speak-EPUB-1.0.0/adapters/base.py` + `Speak-EPUB-1.0.0/adapters/novelphoenix.py` — define `ScraperPort` ABC (search/listChapters/fetchChapter/getSelectors) with frozen DTOs, OS-aware `get_venv_python()` (`Scripts/python.exe` Win vs `bin/python` posix), skeleton adapter implementing ABC raising NotImplemented, helper `guess_adapter` — rationale AD-1/AD-5/AD-9 port-direction gate
- [x] `Speak-EPUB-1.0.0/adapters/overrides/.gitkeep` + import-linter config (`.importlinter` or `pyproject.toml` [importlinter]) — create overrides dir, add contract forbidding `core → adapters.*` and `adapters → core.pipeline` — rationale AD-1 enforcement
- [x] `src-tauri/src/sidecar.ts` (or `src/lib/sidecar.ts`) + `docs/sidecar-fallback.md` — JSON-RPC stdin/stdout `{"id","method","params"}` round-trip spike (10-min proof), `app.emit("python_sidecar_call")` → python `core/config.py` `handle_rpc`, document HTTP fallback `localhost:17381` if spike fails — rationale AD-4 spike + AD-6 bus
- [x] Verification + docs — `npm run build` + `cargo check` + `Speak-EPUB-1.0.0/venv/Scripts/python.exe -m py_compile Speak-EPUB-1.0.0/core/ports.py Speak-EPUB-1.0.0/core/config.py` green, update `README.md` scaffold section with `npm run tauri dev` and venv path note

**Acceptance Criteria:**
- Given clean repo without `src-tauri/` and `Speak-EPUB-1.0.0/core/`, when `npm run tauri dev` (or `cargo tauri dev`) after scaffold, then 960px window opens, DESIGN.md tokens render as CSS vars (ring `#2B5CE6`, rounded `md 8px`, mono `JetBrains Mono 12`), and locale auto-detect shows `pl.json` on `pl` system else `en` — no hardcoded strings.
- Given `core/ports.py` defines `ScraperPort.search/listChapters/fetchChapter/getSelectors`, when `adapters/novelphoenix.py` imports and implements it, then import linter (`lint:imports`) passes and direct `core → adapters.*` or `adapters → core.pipeline` import fails with file:line error.
- Given `core/config.py:get_venv_python()`, when run on Windows, then returns `Speak-EPUB-1.0.0/venv/Scripts/python.exe`; when `os.name != 'nt'` then `Speak-EPUB-1.0.0/venv/bin/python`; `tauri-plugin-shell` spawns that exact path and JSON-RPC `{"method":"ping"}` returns `{"result":"pong"}` over stdin/stdout; fallback HTTP doc exists at `docs/sidecar-fallback.md`.
- Given no network calls in this story, when adapter methods `search/listChapters/fetchChapter` called, then they raise `NotImplementedError("mock only — Epic 1.2 implements")` and `getSelectors()` returns `Selectors(start=None, end=None)` skeleton.
- Given `store.json` via `tauri-plugin-store`, when app launches with existing `store.json` containing `{"voice":"pl-PL-ZofiaNeural","parallel":3}`, then `core/config.py:load_store()` mirrors those values and GUI Settings placeholder reads same keys (no divergence from CLI flags).

## Spec Change Log


## Verification

**Commands:**
- `npm run build` -- expected: Vite build success, no TS errors, tokens included in CSS
- `cargo check --manifest-path src-tauri/Cargo.toml` -- expected: Tauri 2.11.5 + shell/store plugins resolve, no errors
- `Speak-EPUB-1.0.0/venv/Scripts/python.exe -m py_compile Speak-EPUB-1.0.0/core/ports.py Speak-EPUB-1.0.0/core/config.py Speak-EPUB-1.0.0/adapters/novelphoenix.py` -- expected: 0 exit, ABC importable
- `Speak-EPUB-1.0.0/venv/Scripts/python.exe -c "from core.ports import ScraperPort; from adapters.novelphoenix import NovelPhoenixAdapter; print(issubclass(NovelPhoenixAdapter, ScraperPort))"` -- expected: `True`
- `Speak-EPUB-1.0.0/venv/Scripts/python.exe -c "import core.config; print(core.config.get_venv_python())"` -- expected on Win: path ends with `Scripts\\python.exe`
- `npm run lint:imports` (or `lint-imports --config .importlinter`) -- expected: contract passes; inject violating import → fails pointing at violating file
- `cargo tauri dev -- --help` (smoke) / `npm run tauri -- --help` -- expected: Tauri CLI 2.11.4 recognized

**Manual checks (if no CLI):**
- `npm run tauri dev` opens 960px window, light bg `#F8F9FA`, accent `#2B5CE6` visible on button, `JetBrains Mono 12` in mono sample, window resizable not below 900px, switch system language pl↔en and relaunch → UI strings flip without rebuild

## Suggested Review Order

**Contract — Port & venv**

- ScraperPort ABC is the dependency firewall — read it first
  [`ports.py:42`](../../Speak-EPUB-1.0.0/core/ports.py#L42)

- OS-aware venv path prevents bare python drift
  [`config.py:17`](../../Speak-EPUB-1.0.0/core/config.py#L17)

- Skeleton proves direction core←adapter without network
  [`novelphoenix.py:11`](../../Speak-EPUB-1.0.0/adapters/novelphoenix.py#L11)

- Fallback guessing uses host-suffix not query string
  [`base.py:19`](../../Speak-EPUB-1.0.0/adapters/base.py#L19)

**Sidecar — JSON-RPC spike**

- Rust resolve mirrors Python get_venv_python (parity critical)
  [`lib.rs:55`](../../src-tauri/src/lib.rs#L55)

- Real spawn hello now returns pong:true matching Python handle_rpc
  [`lib.rs:89`](../../src-tauri/src/lib.rs#L89)

- Python handle_rpc guards non-dict and maps id correctly
  [`config.py:103`](../../Speak-EPUB-1.0.0/core/config.py#L103)

- Frontend handles both Error and string throws + id mismatch
  [`sidecar.ts:38`](../../src/lib/sidecar.ts#L38)

**UI — tokens & i18n**

- Tokens as JS source of truth for Tailwind
  [`tokens.ts:6`](../../src/styles/tokens.ts#L6)

- CSS vars expose light/dark pairs and @theme inline
  [`globals.css:3`](../../src/styles/globals.css#L3)

- i18n auto-detect pl/en with no hardcoded strings
  [`i18n/index.ts:1`](../../src/i18n/index.ts#L1)

- 960px shell demos tokens and sidecar status
  [`App.tsx:1`](../../src/App.tsx#L1)

**Tauri shell & config**

- Tauri 2.11.5 + shell/store plugins and 960/min900 window
  [`Cargo.toml:9`](../../src-tauri/Cargo.toml#L9)

- Window and bundle config single per OS
  [`tauri.conf.json:1`](../../src-tauri/tauri.conf.json#L1)

- Import linter enforces AD-1 both directions
  [`.importlinter:1`](../../.importlinter#L1)

- Docs capture HTTP fallback for when shell spawn fails
  [`sidecar-fallback.md:1`](../../docs/sidecar-fallback.md#L1)
