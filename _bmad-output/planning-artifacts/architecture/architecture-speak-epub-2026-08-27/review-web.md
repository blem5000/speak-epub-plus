# Review — Web Research & Version Reality Check

**Lens:** Verify every committed decision was web-researched or reality-checked

## Verdict: strong

All pinned versions were checked live 2026-08-27:

- Tauri 2.11.5 (Jul 1 2026) + api 2.11.1 + cli 2.11.4 via v2.tauri.app/release — confirmed
- edge-tts 7.2.8 (Mar 22 2026 PyPI) matches requirements.txt — confirmed
- ebooklib 0.20, beautifulsoup4 4.14.3, lxml 6.0.2 — existing venv pins ratified
- create-tauri-app 4.7.3 and plugins store/shell 2.x marked [ASSUMPTION] — correctly flagged unverified

No out-of-date binding. Remaining assumptions explicitly tagged.

## Findings
- [low] tauri-plugin-store/shell versions 2.x not separately web-verified — acceptable, pin exact at impl
