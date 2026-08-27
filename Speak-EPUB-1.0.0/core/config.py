"""
core/config.py — OS-aware venv path + store.json mirror + sidecar JSON-RPC handler.
AD-4, AD-10: Never bare `python`; single store.json via tauri-plugin-store.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

# ---------------------------------------------------------------------------
# Venv resolution — OS-aware (AGENTS.md)
# ---------------------------------------------------------------------------

def get_venv_python() -> str:
    """
    Return OS-aware venv python path.
    Windows: Speak-EPUB-1.0.0/venv/Scripts/python.exe
    POSIX  : Speak-EPUB-1.0.0/venv/bin/python
    """
    # Resolve relative to project root (two levels up from this file if run as module,
    # but we return the spec-expected relative string for Tauri shell spawn)
    if os.name == "nt":
        return "Speak-EPUB-1.0.0/venv/Scripts/python.exe"
    return "Speak-EPUB-1.0.0/venv/bin/python"


def get_venv_python_abs() -> Path:
    """Absolute path to venv python for local checks."""
    base = Path(__file__).resolve().parents[2]  # repo root
    rel = get_venv_python()
    return base / rel


# ---------------------------------------------------------------------------
# Store — single JSON mirroring CLI flags (AD-10)
# ---------------------------------------------------------------------------

DEFAULT_STORE: Dict[str, Any] = {
    "voice": "en-US-AndrewNeural",
    "rate": "+0%",
    "parallel": 3,
    "chunk-size": 3500,
    "retries": 5,
    "scrapeDelay": 4000,
    "safeMode": False,
    "keepEPUB": True,
    "keepMP3": True,
    "keepM4B": True,
    "filters": [],
}


def get_store_path() -> Path:
    """
    Resolve store.json path.
    Tauri store defaults to app config dir; for CLI parity we also check
    ./store.json and Speak-EPUB-1.0.0/store.json.
    """
    # Prefer Tauri app config dir if available via env (fallback to local)
    # For sidecar, use repo-root store.json
    for candidate in [
        Path("store.json"),
        Path("Speak-EPUB-1.0.0/store.json"),
        Path.home() / ".config" / "speak-epub" / "store.json",
    ]:
        if candidate.is_file():
            return candidate
    # Default location for new store
    return Path("store.json")


def load_store() -> Dict[str, Any]:
    """Load store.json and merge with defaults (mirrors CLI flags)."""
    path = get_store_path()
    data: Dict[str, Any] = dict(DEFAULT_STORE)
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data.update(raw)
        except Exception:
            pass
    return data


def save_store(patch: Any) -> Dict[str, Any]:
    """Merge patch into store.json and persist atomically."""
    if not isinstance(patch, dict):
        raise TypeError("patch must be dict")
    path = get_store_path()
    current = load_store()
    current.update(patch)
    # validate JSON serializable before writing
    try:
        payload = json.dumps(current, indent=2, ensure_ascii=False)
    except TypeError as e:
        raise TypeError(f"patch not JSON serializable: {e}") from e
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(path)
    except OSError as e:
        raise OSError(f"store write failed {path}: {e}") from e
    return current


# ---------------------------------------------------------------------------
# JSON-RPC handler — stdin/stdout primary (AD-4 spike)
# ---------------------------------------------------------------------------

def handle_rpc(request: Any) -> Dict[str, Any]:
    """
    Handle a single JSON-RPC request dict {id, method, params}.
    Returns response dict {id, result} or {id, error}.
    Spike supports ping/hello; other methods return NotImplemented mock.
    """
    if not isinstance(request, dict):
        return {"id": "0", "error": {"code": "BAD_REQUEST", "message": "request must be object"}}
    rid = request.get("id", "0")
    method = request.get("method")

    if method == "ping":
        return {"id": rid, "result": "pong"}
    if method == "hello":
        return {"id": rid, "result": {"echo": request.get("params"), "pong": True}}

    # For future methods, indicate mock only
    return {
        "id": rid,
        "error": {"code": "NOT_IMPLEMENTED", "message": "mock only — Epic 1.2 implements"},
    }


def run_sidecar_loop() -> None:
    """Run JSON-RPC loop over stdin/stdout (line-delimited JSON)."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        if len(line) > 1_000_000:
            resp = {"id": "0", "error": {"code": "TOO_LARGE", "message": "line exceeds 1MB"}}
            try:
                sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
                sys.stdout.flush()
            except BrokenPipeError:
                break
            continue
        try:
            req = json.loads(line)
            # preserve id for error correlation even if req is not dict
            rid = req.get("id", "0") if isinstance(req, dict) else "0"
            resp = handle_rpc(req)
            # ensure response id matches request when handle_rpc returns BAD_REQUEST with 0
            if isinstance(req, dict) and "id" in req and resp.get("id") == "0" and rid != "0":
                resp["id"] = rid
        except Exception as e:
            # try to extract id from raw JSON for correlation
            try:
                raw = json.loads(line)
                rid2 = raw.get("id", "0") if isinstance(raw, dict) else "0"
            except Exception:
                rid2 = "0"
            resp = {"id": rid2, "error": {"code": "EXCEPTION", "message": str(e)}}
        try:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
        except BrokenPipeError:
            break


if __name__ == "__main__":
    # Allow `python -m core.config` or `python core/config.py` to run loop
    # Add Speak-EPUB-1.0.0 parent to path when executed directly
    run_sidecar_loop()
