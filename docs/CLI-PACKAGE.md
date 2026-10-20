# Speak EPUB CLI (self-contained)

This package converts an EPUB book into an audiobook with the same pipeline
as the desktop app — no Python setup required.

## Run it

**Windows**

```
speak.cmd "book.epub" --m4b
```

**macOS / Linux**

```
chmod +x speak.sh
./speak.sh "book.epub" --m4b
```

The first run downloads the Python runtime (~40 MB) into
`%LOCALAPPDATA%\speak-epub\runtime` (or `~/.local/share/speak-epub/runtime`)
and reuses it afterwards. The runtime is the same release asset the desktop
app uses, so a machine that already has the app installed downloads
nothing extra.

If you have Python 3.10+ and prefer your own environment, run the script
directly:

```
python speak.py "book.epub" --m4b
```

## Options

Run `speak.cmd --help` (or `python speak.py --help`) for the full list.
The most used ones:

| option | meaning |
|---|---|
| `--m4b` / `--m4a` | one audiobook file with chapter markers (needs FFmpeg) |
| `--start-chapter N` / `--end-chapter N` | convert a range only |
| `--voice NAME` | Edge TTS voice (default `en-US-AndrewNeural`) |
| `--parallel N` | TTS parts in flight (2–3 recommended) |
| `--engine auto\|edge\|local` | Edge (cloud) or Piper (offline) |
| `--normalize-audio` / `--trim-silence` | podcast-grade post-processing |

## Notes

- FFmpeg is only needed for merging chapters and for `--m4b` / `--m4a`.
- The local (Piper) engine needs its components and a voice model; the
  desktop app offers a one-click download for both.
