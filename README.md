# speak-epub-plus

Convert any EPUB file into a spoken-word audiobook using Microsoft Edge's free neural text-to-speech voices. Outputs one MP3 per chapter, with an optional single M4B or M4A file with chapter markers.

> **Attribution:** This is a new standalone project built on top of **Speak EPUB** by **Michael Sanford** (MIT, 2026).  
> It is **not a GitHub fork** by design — the project is expected to diverge significantly — but it preserves the original MIT copyright notice.  
> See [`NOTICE.md`](NOTICE.md) and [`LICENSE.md`](LICENSE.md) for details. The original CLI snapshot is preserved at `docs/original-speak-epub-readme.md`. The release procedure (tiers, signing key, the two Tauri traps) is in [`docs/RELEASING.md`](docs/RELEASING.md).

## Features

- **Chapter ranges** — convert the whole book or only selected chapters (`--start-chapter` / `--end-chapter`)
- **No truncation** — long chapters are automatically split into parts and merged afterwards, so Edge TTS never cuts them off
- **Parallel generation** — several TTS requests run at the same time via a global queue (`--parallel`)
- **Listen to a sample before committing** — Settings synthesizes a short clip of the selected voice/engine/rate
- **Two-voice dialogue mode** — quoted dialogue can switch to a second Edge voice (`--dialogue-voice`)
- **Podcast-grade post-processing** — optional loudness normalization and edge-silence trimming of finished chapter files (`--normalize-audio`, `--trim-silence`)
- **Metadata + cover in M4B** — author name and cover art are embedded in the audiobook file
- **Batch mode** — convert several EPUBs in a single command (CLI)
- **Resume anywhere** — finished chapters and parts are skipped on re-run; if a run fails, just repeat the same command
- **Single-file audiobooks** — optional M4B/M4A output with real chapter markers (requires FFmpeg)
- **Desktop app** — full GUI (find → preview → filters → EPUB build → TTS queue → M4B) driving the same core pipeline through a Python sidecar — see [Desktop app](#desktop-app-tauri--python-sidecar)

## How it works

1. Extracts text from each chapter in the EPUB (EPUBs are ZIP files containing HTML)
2. Splits each chapter into parts (default 3,500 characters) at sentence boundaries so long chapters are never truncated by Edge TTS
3. Sends all parts through a parallel worker queue to Microsoft Edge TTS (the same engine behind Windows Narrator and Edge's Read Aloud) — free, no API key required
4. Merges the parts back into one numbered MP3 per chapter (requires FFmpeg; without it, the individual part files are kept)
5. Optionally combines all chapters into a single `.m4b` or `.m4a` audiobook file with chapter markers using FFmpeg

## Requirements

- Python 3.10+
- FFmpeg on your PATH (only needed for `--m4b` / `--m4a`)

> No FFmpeg? The app auto-repairs itself: it downloads a portable build to
> `%LOCALAPPDATA%\speak-epub\ffmpeg` (per-user, no admin rights) once and
> reuses it afterwards. A manual install below is still fine and preferred.
>
> The desktop app works the same way: the Python runtime it needs is
> downloaded **once** on the first launch (~40 MB) into
> `%LOCALAPPDATA%\speak-epub\runtime\<hash>` and reused by every later
> update. App updates therefore transfer only the app itself (~15 MB) — the
> runtime is re-downloaded only when the dependencies actually change.
>
> The optional **local TTS engine** (Piper + the ONNX runtime, ~60 MB) is a
> separate download: if you stay on Edge TTS you never fetch it. Settings →
> TTS engine offers it when the local engine is missing.

## Installation

Clone or download the project, then follow the steps for your OS.

### Windows

```powershell
cd speak-epub-plus

python -m venv venv
& .\venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

**For M4B/M4A output**, install FFmpeg:
```powershell
winget install ffmpeg
```

> If you see a script execution policy error, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` first.

### macOS

```bash
cd speak-epub-plus

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
```

**For M4B/M4A output**, install FFmpeg via Homebrew:
```bash
brew install ffmpeg
```

> If Homebrew is not installed: `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"`

### Linux

```bash
cd speak-epub-plus

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
```

**For M4B/M4A output**, install FFmpeg via your package manager:
```bash
# Debian/Ubuntu
sudo apt install ffmpeg

# Fedora
sudo dnf install ffmpeg

# Arch
sudo pacman -S ffmpeg
```

## Usage

```sh
# Basic conversion (outputs chapter MP3s into a folder)
python speak.py "path/to/book.epub"

# Also produce a single M4B audiobook with chapter markers
python speak.py "path/to/book.epub" --m4b

# Or M4A (better compatibility with some Android players)
python speak.py "path/to/book.epub" --m4a

# Choose a different voice
python speak.py "path/to/book.epub" --voice en-US-AriaNeural

# Convert only chapters 36-40
python speak.py "path/to/book.epub" --start-chapter 36 --end-chapter 40 --m4b

# Convert from chapter 36 to the end of the book, with 3 parallel TTS jobs
python speak.py "path/to/book.epub" --start-chapter 36 --parallel 3

# Lower the part size if you still hear truncation
python speak.py "path/to/book.epub" --chunk-size 2000

# Custom output folder name
python speak.py "path/to/book.epub" --output my_audiobook

# Second voice for quoted dialogue (narration keeps the main voice)
python speak.py "path/to/book.epub" --dialogue-voice pl-PL-ZofiaNeural

# Podcast-grade processing: loudness normalization + edge-silence trimming
python speak.py "path/to/book.epub" --normalize-audio --trim-silence

# Several books in one command (each gets its own output folder)
python speak.py "book1.epub" "book2.epub" --m4b

# List all available English voices
python speak.py --list-voices

# List voices for all languages
python speak.py --list-voices --all-languages
```

The default voice is `en-US-AndrewNeural` (American male). Run `--list-voices` to browse available English voices, or add `--all-languages` to see all languages.

## Options reference

| Option | Default | Description |
|---|---|---|
| `--voice` | `en-US-AndrewNeural` | Edge TTS voice name |
| `--output` | `<epub_name>_audiobook` | Output folder name |
| `--m4b` / `--m4a` | off | Combine chapter MP3s into a single audiobook file (requires FFmpeg) |
| `--start-chapter` | `1` | First extracted chapter number to convert |
| `--end-chapter` | last chapter | Stop after this extracted chapter number |
| `--chunk-size` | `3500` | Maximum characters per TTS request (Edge and local); lower it if output gets truncated |
| `--parallel` | `3` | Starting number of TTS parts generated at the same time. Edge TTS auto-scales 1–12 while running (backs off on throttling); the local Piper engine uses CPU cores instead |
| `--retries` | `5` | Retries per failed TTS request/part (Edge and local) |
| `--rate` | `+0%` | Speech rate like `+25%` or `-10%` (clamped to ±100%) |
| `--engine` | `auto` | TTS engine: `auto` (local Piper on fast CPUs once its voice is downloaded, else Edge), `edge` (cloud), `local` (offline Piper) |
| `--local-voice` | default voice | Piper voice for the local engine, e.g. `pl_PL-darkman-medium` (downloaded on demand into `Documents\speak-epub\models`) |
| `--dialogue-voice` | off | Second Edge TTS voice for quoted dialogue („…", "…", «…»); narration keeps `--voice`. Edge engine only. A 1-second pause is appended after each chapter title that is attached to them |
| `--normalize-audio` | off | Normalize chapter loudness to podcast levels (FFmpeg loudnorm, requires FFmpeg) |
| `--trim-silence` | off | Trim long (>2 s) leading/trailing digital silence of each chapter (below -60 dB; speech pacing and mid-chapter pauses are kept) |
| `--keep-parts` | off | Keep the temporary `_parts` MP3 files after merging |
| `--list-voices` | – | List English voices (`--all-languages`: every language) |

Chapter numbers are counted in spine (reading) order across the whole EPUB — near-empty pages like covers and TOCs are skipped.

Re-running the same command resumes — generated files carry a build manifest (`.speak-epub-build.json`); changing rate/voice/engine/dialogue voice/processing flags between runs automatically wipes and regenerates the audio so old settings never leak into new files.

## Output

```
my_book_audiobook/
├── 001_Introduction.mp3
├── 002_Chapter_One.mp3
├── 003_Chapter_Two.mp3
├── ...
└── my_book.m4b          # only with --m4b or --m4a
```

If you re-run the script, any chapter MP3 (or part file) that already exists is skipped — only missing pieces are generated. This means interrupted or failed runs can be resumed with the exact same command. When converting a chapter range, the M4B/M4A filename includes that range, e.g. `my_book_chapters_036_to_040.m4b`.

## Voices

A selection of recommended voices:

| Voice | Gender | Accent |
|---|---|---|
| `en-US-AndrewNeural` | Male | American *(default)* |
| `en-GB-RyanNeural` | Male | British |
| `en-GB-SoniaNeural` | Female | British |
| `en-US-AriaNeural` | Female | American |
| `en-US-GuyNeural` | Male | American |
| `en-AU-WilliamMultilingualNeural` | Male | Australian |

Run `python speak.py --list-voices` for the full English list, or `--list-voices --all-languages` for all languages.

## Desktop app (Tauri + Python sidecar)

The repository contains a full desktop app — a React + Tauri GUI driving the same core pipeline as the CLI through a Python JSON-RPC sidecar.

Prerequisites: Node 24+, Rust 1.77+, Python 3.10+, FFmpeg on PATH.

```bash
# install frontend
npm install
# dev with Tauri shell (window 960px / min 900)
npm run tauri dev
# or just Vite
npm run dev
# typecheck + production bundle
npm run build
```

**App features**

- **Find** — search web novels via site adapters (aggregator with per-adapter fault isolation); results table with title, chapter count and cover
- **Chapter list** — spine-ordered chapters with from/to range and per-chapter checkboxes
- **Preview** — polite fetching with a raw-HTML resume cache and selector-based content isolation; Original/Cleaned tabs with XSS-sanitized rendering (DOMPurify)
- **Filters** — plain/regex line filters applied once at the EPUB build gate; CRUD persisted in `store.json`, live preview with removed-count
- **EPUB build** — EPUB assembly with epubcheck validation and a result card (Open uses a path-scoped opener permission)
- **TTS queue** — Edge TTS parts through a global parallel queue (2–3 recommended) with live progress events, throttle badge, retry/backoff; finished parts are skipped on re-run
- **M4B/M4A** — per-chapter merge plus a single audiobook file with chapter markers (FFmpeg)
- **Settings** — persisted atomically to `store.json`; UI locale auto-detects `pl`/`en` from `navigator.language` (fallback `en`)
- **Automatic updates** — the app checks for a newer release on startup and installs it in place; the update manifest is signed, so a substituted payload is rejected (a portable build has no installer and is sent to the release page instead)

**Downloads on the first launch**

The app tier (the executable plus the Python `core`/`adapters` code) is only
~5 MB. The Python **runtime tier** (~41 MB) is downloaded once and cached in
`%LOCALAPPDATA%\speak-epub\runtime\<hash>`; the optional **local TTS
engine** (~60 MB, Piper + ONNX) is fetched only when you turn the local
engine on. Later updates transfer the app tier alone.

**Architecture**

The GUI (`src/`) talks JSON-RPC over stdio to the Python sidecar (`core/config.py:handle_rpc`), which orchestrates the core pipeline: `core/fetch.py` (polite fetching, resume cache, adaptive 429) → `core/clean.py` (selector isolation) → `core/filters.py` (plain/regex filters) → `core/epub.py` (assembly) → `core/tts.py` (chunking, PartJob queue, FFmpeg merge). The dependency direction (GUI → Core → Port → Adapter) is enforced by import-linter (`npm run lint:imports`). Tauri capabilities are least-privilege: shell permissions are removed and the opener is scoped to `**/*.epub` plus the output directory (`src-tauri/capabilities/default.json`).

Python sidecar path is OS-aware via `core/config.py:get_venv_python()`:

- Windows: `venv/Scripts/python.exe`
- macOS/Linux: `venv/bin/python`

Never use bare `python`; always spawn via that path (see `docs/sidecar-fallback.md` for the HTTP fallback on `http://localhost:17381` if stdin/stdout spawn fails).

**Testing**

```bash
# frontend units (vitest)
npm test
# core + adapters + sidecar (pytest; always via the venv interpreter)
venv/Scripts/python.exe -m pytest tests
# architecture contracts (import-linter)
npm run lint:imports
# sanity-check core contracts
venv/Scripts/python.exe -m py_compile core/ports.py core/config.py
cargo check --manifest-path src-tauri/Cargo.toml
```

**Politeness towards the site**

The fetcher reads the site's `robots.txt` and follows it: a path the site
disallows for the app's user agent is not requested, and the site's
`Crawl-delay` (when present) is respected on top of the built-in 3–5 s pause
between chapters. Requests to the same host are paced by a per-host limiter,
so a long book never hammers the site. A missing or unreachable
`robots.txt` means "no restrictions" (the standard behaviour) and never
blocks a conversion.

**Design system**

Design tokens from `_bmad-output/planning-artifacts/ux-designs/` are exposed as CSS vars in `src/styles/globals.css` (`--background #F8F9FA`, `--ring #2B5CE6`, `--radius-md 8px`, `--font-mono JetBrains Mono 12px`) and via `src/styles/tokens.ts` / Tailwind theme. The UI meets WCAG 2.1 AA state-contrast requirements and is responsive down to narrow widths.

## Credits & License

- Original project: **Speak EPUB** by **Michael Sanford** — MIT License, Copyright (c) 2026 Michael Sanford
- This derivative (`speak-epub-plus`): Copyright (c) 2026 blem5000 and contributors — also MIT

See [LICENSE.md](LICENSE.md) (preserves original MIT notice) and [NOTICE.md](NOTICE.md) for attribution details.
