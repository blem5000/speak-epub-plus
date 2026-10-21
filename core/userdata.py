"""Per-user data that is not a setting: the library, the search history and
the pronunciation dictionary.

The store (`store.json`) mirrors the CLI flags — it is settings. The three
features here are data the user accumulates, so they live in their own files
next to the store:

* `library.json` — the audiobooks that were produced
* `search-history.json` — the recent searches
* `pronunciation.json` — the pronunciation dictionary

Every write is atomic (temp file + replace) and a corrupt file is reported,
never silently reset.
"""
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

#: The maximum number of remembered searches.
MAX_HISTORY = 20

#: The maximum number of library entries.
MAX_LIBRARY = 500


def user_data_dir() -> Path:
    """The per-user data directory (the same one that holds store.json)."""
    override = os.environ.get("SPEAK_EPUB_STORE")
    if override and override.strip():
        return Path(override).parent
    if os.name == "nt":
        base = os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "speak-epub"


def data_path(name: str) -> Path:
    return user_data_dir() / name


def read_json(name: str, default: Any) -> Any:
    """Read a JSON file; a corrupt file yields the default (never raises)."""
    path = data_path(name)
    try:
        if not path.is_file():
            return default
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw
    except Exception:
        return default


def write_json(name: str, payload: Any) -> bool:
    """Write a JSON file atomically. Returns False when it could not be written."""
    path = data_path(name)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
        return True
    except OSError:
        return False
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Search history
# ---------------------------------------------------------------------------

def get_search_history() -> List[Dict[str, Any]]:
    raw = read_json("search-history.json", [])
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in raw:
        if isinstance(item, str):
            out.append({"query": item[:200], "at": 0})
            continue
        if not isinstance(item, dict):
            continue
        query = str(item.get("query") or "").strip()
        if not query:
            continue
        try:
            at = int(item.get("at", 0))
        except (TypeError, ValueError):
            at = 0
        out.append({"query": query[:200], "at": at})
    return out[:MAX_HISTORY]


def add_search_history(query: str) -> List[Dict[str, Any]]:
    """Remember a search (most recent first, de-duplicated)."""
    text = str(query or "").strip()
    if not text:
        return get_search_history()
    entry = {"query": text[:200], "at": int(time.time())}
    history = [h for h in get_search_history() if h.get("query", "").lower() != text.lower()]
    history.insert(0, entry)
    history = history[:MAX_HISTORY]
    write_json("search-history.json", history)
    return history


def clear_search_history() -> List[Dict[str, Any]]:
    write_json("search-history.json", [])
    return []


# ---------------------------------------------------------------------------
# Library — the audiobooks that were produced
# ---------------------------------------------------------------------------

def get_library() -> List[Dict[str, Any]]:
    raw = read_json("library.json", [])
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        entry = {
            "id": str(item.get("id") or path),
            "title": str(item.get("title") or Path(path).name),
            "author": str(item.get("author") or ""),
            "cover": str(item.get("cover") or ""),
            "path": path,
            "format": str(item.get("format") or ""),
            "size": int(item.get("size") or 0),
            "chapters": int(item.get("chapters") or 0),
            "sourceUrl": str(item.get("sourceUrl") or ""),
            "createdAt": int(item.get("createdAt") or 0),
        }
        out.append(entry)
    return out


def add_library_entry(entry: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Add (or replace) a library entry — the same path is replaced, not duplicated."""
    if not isinstance(entry, dict):
        return get_library()
    path = str(entry.get("path") or "").strip()
    if not path:
        return get_library()
    item = {
        "id": str(entry.get("id") or path),
        "title": str(entry.get("title") or Path(path).name)[:300],
        "author": str(entry.get("author") or "")[:200],
        "cover": str(entry.get("cover") or "")[:2000],
        "path": path,
        "format": str(entry.get("format") or "")[:20],
        "size": int(entry.get("size") or 0),
        "chapters": int(entry.get("chapters") or 0),
        "sourceUrl": str(entry.get("sourceUrl") or "")[:2000],
        "createdAt": int(entry.get("createdAt") or int(time.time())),
    }
    library = [e for e in get_library() if e.get("path") != path]
    library.insert(0, item)
    library = library[:MAX_LIBRARY]
    write_json("library.json", library)
    return library


def remove_library_entry(path: str) -> List[Dict[str, Any]]:
    target = str(path or "").strip()
    library = [e for e in get_library() if e.get("path") != target]
    write_json("library.json", library)
    return library


# ---------------------------------------------------------------------------
# Pronunciation dictionary
# ---------------------------------------------------------------------------

#: A pronunciation replacement: "Arystoteles" -> "ary-stoteles".
PronunciationEntry = Dict[str, str]


def get_pronunciation() -> List[PronunciationEntry]:
    raw = read_json("pronunciation.json", [])
    if not isinstance(raw, list):
        return []
    out: List[PronunciationEntry] = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        source = str(item.get("from") or "").strip()
        target = str(item.get("to") or "").strip()
        if not source or not target:
            continue
        key = source.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"from": source[:100], "to": target[:200]})
    return out


def set_pronunciation(entries: Any) -> List[PronunciationEntry]:
    if not isinstance(entries, list):
        return get_pronunciation()
    cleaned: List[PronunciationEntry] = []
    seen = set()
    for item in entries:
        if not isinstance(item, dict):
            continue
        source = str(item.get("from") or "").strip()
        target = str(item.get("to") or "").strip()
        if not source or not target:
            continue
        key = source.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append({"from": source[:100], "to": target[:200]})
    write_json("pronunciation.json", cleaned)
    return cleaned


def _word_pattern(source: str) -> "re.Pattern[str]":
    """Match the source as a whole word, whatever the case."""
    return re.compile(rf"(?<!\w){re.escape(source)}(?!\w)", re.IGNORECASE)


def apply_pronunciation(text: str, entries: Optional[List[PronunciationEntry]] = None) -> str:
    """Replace the words of the dictionary with their reading.

    The replacement is a plain text substitution (not SSML): it works with
    every engine, including the local Piper one. The longer sources are
    replaced first so "Jan Kowalski" wins over "Jan".
    """
    if not text or not isinstance(text, str):
        return text
    if entries is None:
        entries = get_pronunciation()
    if not entries:
        return text
    ordered = sorted(entries, key=lambda e: len(str(e.get("from", ""))), reverse=True)
    out = text
    for entry in ordered:
        source = str(entry.get("from", "")).strip()
        target = str(entry.get("to", "")).strip()
        if not source or not target:
            continue
        try:
            out = _word_pattern(source).sub(target.replace("\\", r"\\"), out)
        except re.error:
            continue
    return out
