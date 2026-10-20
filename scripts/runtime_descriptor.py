#!/usr/bin/env python3
"""Describe the Python sidecar runtime (the "runtime tier").

The desktop app is split into two tiers:

- **app tier** (~15 MB): the Tauri executable plus our `core`/`adapters`
  code. It changes with every release.
- **runtime tier** (~250 MB): the embedded CPython interpreter and its
  dependencies. It changes only when the interpreter or `requirements.txt`
  changes — so it is downloaded ONCE and cached in the user profile.

The cache key is a hash of everything that can change the runtime's
behaviour: the descriptor format version, the exact interpreter build and
the dependency set. As long as those stay the same, an app update does NOT
re-download the runtime.

Usage:
    python scripts/runtime_descriptor.py --python-version 3.11.17+20261013 \
        --requirements requirements.txt --out src-tauri/sidecar-runtime/runtime.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

#: Bump when the runtime layout changes (the app refuses an unknown format).
RUNTIME_FORMAT_VERSION = 1

#: Where the runtime asset lives (the app fills in its own version).
RELEASE_URL_TEMPLATE = (
    "https://github.com/blem5000/speak-epub-plus/releases/download/v{version}/{asset}"
)


def requirements_sha256(requirements_text: str) -> str:
    """Digest of the dependency set (whitespace-insensitive)."""
    normalized = "\n".join(
        line.strip() for line in requirements_text.replace("\r\n", "\n").split("\n")
        if line.strip() and not line.strip().startswith("#")
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def runtime_hash(python_version: str, req_sha: str) -> str:
    """Cache key of the runtime: interpreter build + dependency set."""
    payload = f"v{RUNTIME_FORMAT_VERSION}\n{python_version.strip()}\n{req_sha}\n"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def build_descriptor(python_version: str, requirements_text: str) -> dict:
    """The descriptor written next to the app tier (runtime.json)."""
    req_sha = requirements_sha256(requirements_text)
    rh = runtime_hash(python_version, req_sha)
    return {
        "format": RUNTIME_FORMAT_VERSION,
        "hash": rh,
        "python_version": python_version.strip(),
        "requirements_sha256": req_sha,
        "asset": f"speak-epub-runtime-{rh}.zip",
        "url_template": RELEASE_URL_TEMPLATE,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-version", required=True, help="exact interpreter build, e.g. 3.11.17+20261013")
    parser.add_argument("--requirements", default="requirements.txt")
    parser.add_argument("--out", required=True, help="path of the runtime.json to write")
    args = parser.parse_args(argv)

    req_path = Path(args.requirements)
    text = req_path.read_text(encoding="utf-8") if req_path.is_file() else ""
    descriptor = build_descriptor(args.python_version, text)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(descriptor, indent=2) + "\n", encoding="utf-8")
    print(f"runtime {descriptor['hash']} -> {out} (asset {descriptor['asset']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
