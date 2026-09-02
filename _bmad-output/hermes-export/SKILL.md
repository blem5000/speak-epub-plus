---
name: speak-epub-bmad
description: "BMAD context for speak epub — EPUB→M4B via Edge TTS. Exports epics, architecture, specs, and agent personas for Hermes Agent."
version: 1.0.0
author: speak-epub
license: MIT
platforms: [windows, macos, linux]
metadata:
  hermes:
    tags: [bmad, speak-epub, epub, tts, tauri, python]
    related_skills: [opencode, claude-code, codex]
    project_root: "C:/Users/admin/Documents/programowanie/speak epub"
---

# speak-epub — BMAD → Hermes Export

Generated 2026-08-28T10:01:47.663827 from `_bmad/config.toml` and `_bmad-output/`.

## Project
- **Name:** speak epub
- **Output:** `{project-root}/_bmad-output`
- **Agents:** 11
- **Modules:** bmm, bmb, cis

## BMAD Agents (personas)
- **Mary** (`bmad-agent-analyst`) — Business Analyst: Channels Porter's strategic rigor and Minto's Pyramid Principle, grounds every finding in verifiable evidence, represents every stakeholder voice. Speaks like a treasure hunter nar..
- **John** (`bmad-agent-pm`) — Product Manager: Drives Jobs-to-be-Done over template filling, user value first, technical feasibility is a constraint not the driver. Speaks like a detective interrogating a cold case: short quest..
- **Sally** (`bmad-agent-ux-designer`) — UX Designer: Balances empathy with edge-case rigor, starts simple and evolves through feedback, every decision serves a genuine user need. Speaks like a filmmaker pitching the scene before the ..
- **Winston** (`bmad-agent-architect`) — System Architect: Favors boring technology for stability, developer productivity as architecture, ties every decision to business value. Speaks like a seasoned engineer at the whiteboard: measured, ..
- **Amelia** (`bmad-agent-dev`) — Senior Software Engineer: Test-first discipline (red, green, refactor), 100% pass before review, no fluff all precision. Speaks like a terminal prompt: exact file paths, AC IDs, and commit-message brevity —..
- **Sophia** (`bmad-cis-agent-storyteller`) — Master Storyteller: Channels Robert McKee's structural rigor and Joseph Campbell's mythic-arc discipline, grounds every tale in timeless human truths, finds the authentic story before styling the surf..
- **Maya** (`bmad-cis-agent-design-thinking-coach`) — Design Thinking Maestro: Channels Tim Brown's IDEO empathy-first playbook and Don Norman's human-centered rigor, believes design is about THEM not us, treats failure as feedback, designs WITH users not FOR..
- **Carson** (`bmad-cis-agent-brainstorming-coach`) — Elite Brainstorming Specialist: Channels Alex Osborn's brainstorming foundations and Keith Johnstone's improv-born yes-and instinct, knows psychological safety unlocks the wildest ideas, treats today's absurdity ..
- **Dr. Quinn** (`bmad-cis-agent-creative-problem-solver`) — Master Problem Solver: Channels Genrich Altshuller's TRIZ discipline and Donella Meadows's systems-thinking clarity, treats every problem as a system revealing its weakest point, hunts root causes relent..
- **Victor** (`bmad-cis-agent-innovation-strategist`) — Disruptive Innovation Oracle: Channels Clayton Christensen's disruption theory and Kim & Mauborgne's Blue Ocean reframing, believes markets reward genuine new value, calls innovation without business-model thin..
- **Caravaggio** (`bmad-cis-agent-presentation-master`) — Visual Communication + Presentation Expert: Channels Nancy Duarte's presentation architecture and Saul Bass's cinematic graphic instinct, knows visual hierarchy drives attention, cuts every frame that isn't inform-persuade-o..

## Where BMAD artifacts live
- `_bmad-output/planning-artifacts/epics.md` — full epic/story breakdown
- `_bmad-output/planning-artifacts/architecture/` — ARCHITECTURE-SPINE.md
- `_bmad-output/planning-artifacts/ux-designs/` — DESIGN.md / EXPERIENCE.md
- `_bmad-output/specs/spec-speak-epub/SPEC.md` — canonical SPEC
- `_bmad-output/implementation-artifacts/` — sprint-status.yaml + epic context + deferred-work.md
- `AGENTS.md` — bmad:context block (auto-refreshed 2026-08-26)
- `Speak-EPUB-1.0.0/speak.py` — entrypoint (extract_chapters, split_text_for_tts, PartJob queue)

## Usage in Hermes

Hermes will auto-load this skill when working inside this project folder.
It provides:

1. **Project knowledge** — epics, FRs/NFRs, UX-DRs, architecture spine
2. **Agent personas** — Mary (analyst), John (PM), Sally (UX), Winston (architect), Amelia (dev)
3. **Execution invariants** — `max_chars=3500`, parallel 2-3, spine-order chapters, polite fetch, PartJob frozen

## Instructions for Hermes Agent

- Always read `AGENTS.md` bmad:context first.
- For planning: follow `_bmad-output/planning-artifacts/epics.md` epics → stories order, respect NFR1 politeness.
- For building: implement via `bmad-build` workflow semantics — produce working code artifacts per story ACs, verify with `Speak-EPUB-1.0.0/venv\Scripts\python.exe Speak-EPUB-1.0.0/speak.py --help`.
- For architecture questions: canonical is `ARCHITECTURE-SPINE.md`, not ad-hoc docs.

## Export Manifest
- `_bmad-output/planning-artifacts/epics.md` (8000 chars)
- `_bmad-output\planning-artifacts\architecture\architecture-speak-epub-2026-08-27\.memlog.md` (4000 chars)
- `_bmad-output\planning-artifacts\architecture\architecture-speak-epub-2026-08-27\ARCHITECTURE-SPINE.md` (4000 chars)
- `_bmad-output\planning-artifacts\architecture\architecture-speak-epub-2026-08-27\reconcile-addendum.md` (487 chars)
- `_bmad-output\planning-artifacts\architecture\architecture-speak-epub-2026-08-27\reconcile-brief.md` (890 chars)
- `_bmad-output\planning-artifacts\architecture\architecture-speak-epub-2026-08-27\reconcile-ux.md` (547 chars)
- `_bmad-output/specs/spec-speak-epub/SPEC.md` (7734 chars)
- `_bmad-output\planning-artifacts\ux-designs\ux-speak-epub-2026-08-27\.memlog.md` (2897 chars)
- `_bmad-output\planning-artifacts\ux-designs\ux-speak-epub-2026-08-27\DESIGN.md` (4000 chars)
- `_bmad-output\planning-artifacts\ux-designs\ux-speak-epub-2026-08-27\EXPERIENCE.md` (4000 chars)
- `_bmad-output\planning-artifacts\ux-designs\ux-speak-epub-2026-08-27\reconcile-addendum.md` (1157 chars)
- `_bmad-output\planning-artifacts\ux-designs\ux-speak-epub-2026-08-27\reconcile-brief.md` (1694 chars)
- `_bmad-output/implementation-artifacts/sprint-status.yaml` (4624 chars)
