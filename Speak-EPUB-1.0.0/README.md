# Speak EPUB

Convert any EPUB file into a spoken-word audiobook using Microsoft Edge's free neural text-to-speech voices. Outputs one MP3 per chapter, with an optional single M4B or M4A file with chapter markers.

## Features

- **Chapter ranges** — convert the whole book or only selected chapters (`--start-chapter` / `--end-chapter`)
- **No truncation** — long chapters are automatically split into parts and merged afterwards, so Edge TTS never cuts them off
- **Parallel generation** — several TTS requests run at the same time via a global queue (`--parallel`)
- **Resume anywhere** — finished chapters and parts are skipped on re-run; if a run fails, just repeat the same command
- **Single-file audiobooks** — optional M4B/M4A output with real chapter markers (requires FFmpeg)
- **Interactive Windows launcher** — double-click `Run-SpeakEPUB.cmd` (or drag an EPUB onto it), no venv activation needed

## How it works

1. Extracts text from each chapter in the EPUB (EPUBs are ZIP files containing HTML)
2. Splits each chapter into parts (default 3,500 characters) at sentence boundaries so long chapters are never truncated by Edge TTS
3. Sends all parts through a parallel worker queue to Microsoft Edge TTS (the same engine behind Windows Narrator and Edge's Read Aloud) — free, no API key required
4. Merges the parts back into one numbered MP3 per chapter (requires FFmpeg; without it, the individual part files are kept)
5. Optionally combines all chapters into a single `.m4b` or `.m4a` audiobook file with chapter markers using FFmpeg

## Requirements

- Python 3.10+
- FFmpeg on your PATH (only needed for `--m4b` / `--m4a`; the Windows launcher can install it for you via winget)

## Installation

Clone or download the project, then follow the steps for your OS.

### Windows

```powershell
cd speak-epub

python -m venv venv
& .\venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

**For M4B/M4A output**, install FFmpeg:
```powershell
winget install ffmpeg
```

> If you see a script execution policy error, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` first.

#### Windows quick start (interactive)

Prefer not to use the terminal? **Drag any `.epub` file onto `Run-SpeakEPUB.cmd`** and answer two questions — or just double-click `Run-SpeakEPUB.cmd` (or run `Run-SpeakEPUB.ps1` from PowerShell). The launcher will:

- Find a usable Python (`python` or `py -3`) and create `venv` with requirements automatically on first run
- Skip the EPUB prompt when you drag-and-dropped a file
- Remember your last conversion in `last-run.json` and offer to repeat it with a single keypress
- Ask for the EPUB path and output format (MP3 / M4B / M4A)
- Optionally let you set voice, chapter range, parallel jobs, retries, chunk size, output folder, and more
- Offer to install FFmpeg with winget when it is missing and M4B/M4A output is selected
- Let you convert another book without closing the window

### macOS

```bash
cd speak-epub

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
cd speak-epub

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
| `--chunk-size` | `3500` | Maximum characters per Edge TTS request; lower it if output gets truncated |
| `--parallel` | `3` | Number of TTS parts generated at the same time (2–3 recommended; higher may trigger throttling) |
| `--retries` | `5` | Retries per failed TTS request/part |
| `--keep-parts` | off | Keep the temporary `_parts` MP3 files after merging |
| `--list-voices` | – | List English voices (`--all-languages`: every language) |

Chapter numbers are counted in spine (reading) order across the whole EPUB — near-empty pages like covers and TOCs are skipped.

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

## Desktop app

This package preserves the original CLI (`speak.py`) plus the Python core/adapters it depends on. The desktop app (React + Tauri GUI driving this core through a JSON-RPC sidecar) lives at the repository root — see the root [`README.md`](../README.md), section **Desktop app (Tauri + Python sidecar)**, for features, architecture, testing and design-system notes.

## License

MIT — see [LICENSE.md](LICENSE.md)
