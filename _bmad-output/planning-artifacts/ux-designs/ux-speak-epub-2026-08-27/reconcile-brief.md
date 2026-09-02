# Reconcile — brief.md

Source: \_bmad-output/planning-artifacts/briefs/brief-speak-epub-2026-08-27/brief.md\

## Kept (directly reflected in spines)
- Local-first, polite fetch (3-5s + jitter, 10s safe, adaptive on 429), cache/resume conditional -> IA Chapters->Queue, State Patterns (429/throttled/ban), queue adaptive badge (\EXPERIENCE.md:Queue\).
- Title-search aggregator \site|chapters|link\ table, fallback guessing, from-to + checkboxes -> Find + Chapters surfaces.
- Clean EPUB as first-class artifact + optional M4B/M4A with markers, reuse speak.py chunk 3500 / parallel 2-3 / PartJob -> Result surface, Settings keeps.
- Adapter architecture extensible, per-adapter selectors + heuristic fallback + preview pane for correction, user filters plain+regex at EPUB stage -> Preview + Filters surfaces, Component Patterns preview split.
- Cross-platform Tauri, nice GUI, two throttles, keep-switches, logs, Settings persisting all CLI equivalents -> Foundation + Settings.

## Partially kept / transformed
- Cover/TOC/metadata validation (epubcheck) -> Result success badge, not explicit screen -> noted in State Patterns (Build done: epubcheck ✓).
- Chapter count per site in <5s -> Find loading skeleton + subtext.

## Dropped (out-of-scope for UX v1, parked)
- Batch queue of multiple novels, auto-update, cloud sync, mobile, >5-site bulk, collaborative sharing, non-Edge TTS -> not in IA (parked, noted in Foundation no mobile, Scope out).
- None dropped that needed UX surface — intentional park.

## Qualitative ideas not yet materialized
- None — brief is product scope, no visual brand ideas to drop. Visual restraint derived from "schludnie, modern trends" brain dump instead.
