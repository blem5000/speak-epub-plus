# Reconcile — brief.md vs spine

Source: brief.md (6 steps + constraints)

Kept:
- Find aggregator + site|chapters|pick + fallback guessing -> AD-1 Ports & Adapters + aggregator port consumer
- Choose from-to + checkboxes -> AD-5 state ownership + AD-9 resume
- Polite fetch 3-5s+jitter / 10s safe adaptive 429 cache/resume -> AD-3
- Content boundary selectors + preview + heuristic -> AD-7
- Filters plain+regex at EPUB stage -> AD-2
- EPUB build cover/TOC/metadata epubcheck -> AD-8
- TTS reuse chunk 3500 parallel 2-3 PartJob -> brownfield ratification AD-8
- Tauri GUI two throttles voice keep switches Settings persistence -> AD-10, AD-6
- Extensibility adapter without touching core -> paradigm

Dropped: batch queue, paywall logged-session (deferred), cloud sync etc -> correctly in Deferred.

Quiet requirement not dropped: local-only zero data leaves device -> Deployment noted.

