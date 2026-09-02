# Reconcile — addendum.md

Source: \_bmad-output/planning-artifacts/briefs/brief-speak-epub-2026-08-27/addendum.md\

## Kept
- Python sidecar retains ebooklib/edge-tts/lxml and speak.py split/PartJob -> Foundation sidecar IPC.
- Content boundaries per-adapter CSS selectors + heuristic fallback, preview pane required -> Preview surface, State empty-preview.
- Filters plain contains + regex applied at EPUB stage -> Filters table, Preview chip counts.
- Title search titles only, aggregator parallel <5s, fallback guessing -> Find behavior.
- Logged-session cookie/header designed-but-hidden behind experimental flag -> not exposed in main IA, deferred; Settings could hold experimental section later (not in v1 spine).
- Safe vs adaptive delay (10s vs 3-5s+jitter) -> Settings scrape group with preset + custom.
- Tauri ~10MB WebView vs Electron fallback -> Foundation Tauri choice.

## Dropped / deferred
- Electron fallback decision -> not in DESIGN, but Architecture will ratify.
- Filter scope decision (EPUB-only vs audio) -> resolved as EPUB-stage; spine reflects it.

## Gaps
- No visual direction in addendum — UX derived from brain dump trends.
