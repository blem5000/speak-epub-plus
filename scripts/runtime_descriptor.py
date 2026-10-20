#!/usr/bin/env python3
"""Describe the release tiers (runtime tier + optional local-engine tier).

The desktop app is split into three downloadable parts:

- **app tier** (~15 MB): the Tauri executable plus our `core`/`adapters`
  code. It changes with every release.
- **runtime tier** (~40 MB): the embedded CPython interpreter and the
  *core* dependencies. Downloaded ONCE and cached in the user profile.
- **local-engine tier** (~60 MB): Piper + numpy + onnxruntime. Optional —
  fetched only when the user turns the local engine on.

`requirements.txt` is the single source of truth; the `# core` / `# local`
markers split it. The cache key of each tier is a hash of what actually
lands in it, so a tier is re-downloaded only when its own content changes.

Usage:
    python scripts/runtime_descriptor.py --python-version 3.11.17+20261013 \
        --requirements requirements.txt \
        --release-url https://github.com/owner/repo/releases/download/v0.3.10 \
        --out src-tauri/sidecar-runtime/runtime.json \
        --split-out-dir build/requirements
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

#: Bump when the tier layout changes (the app refuses an unknown format).
RUNTIME_FORMAT_VERSION = 2

#: Where the tier assets live ({asset} is replaced by the file name).
RELEASE_URL_TEMPLATE = (
    "https://github.com/blem5000/speak-epub-plus/releases/download/v{version}/{asset}"
)

CORE_MARKER = "# core"
LOCAL_MARKER = "# local"


def split_requirements(requirements_text: str) -> tuple[list[str], list[str]]:
    """Split the requirement file into (core, local) by the section markers.

    Lines before the local marker are core, the rest is local. A file
    without markers is treated as core only. The marker may be written as
    `# local`, `# --- local ---` or `# local engine`.
    """
    core: list[str] = []
    local: list[str] = []
    section = "core"
    for raw in requirements_text.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            # a marker switches the section; other comments are ignored
            key = line.lstrip("#").strip().strip("-").strip().lower()
            if key.startswith("core"):
                section = "core"
                continue
            if key.startswith("local"):
                section = "local"
                continue
            continue
        (local if section == "local" else core).append(line)
    return core, local


def requirements_sha256(lines: list[str]) -> str:
    """Digest of a requirement set (order-insensitive)."""
    normalized = "\n".join(sorted({ln.strip() for ln in lines if ln.strip()}))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _tier_hash(python_version: str, req_sha: str, salt: str) -> str:
    payload = f"v{RUNTIME_FORMAT_VERSION}\n{salt}\n{python_version.strip()}\n{req_sha}\n"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def runtime_hash(python_version: str, req_sha: str) -> str:
    """Cache key of the runtime tier (interpreter + core dependencies)."""
    return _tier_hash(python_version, req_sha, "runtime")


def local_hash(req_sha: str) -> str:
    """Cache key of the optional local-engine tier."""
    return _tier_hash("n/a", req_sha, "local")


def build_descriptor(
    python_version: str,
    requirements_text: str,
    release_url: str | None = None,
) -> dict:
    """The descriptor written next to the app tier (runtime.json)."""
    core, local = split_requirements(requirements_text)
    core_sha = requirements_sha256(core)
    local_sha = requirements_sha256(local)
    rh = runtime_hash(python_version, core_sha)
    lh = local_hash(local_sha)
    url = (release_url or RELEASE_URL_TEMPLATE).rstrip("/")
    return {
        "format": RUNTIME_FORMAT_VERSION,
        "hash": rh,
        "python_version": python_version.strip(),
        "requirements_sha256": core_sha,
        "asset": f"speak-epub-runtime-{rh}.zip",
        "release_url": url,
        "local_hash": lh,
        "local_requirements_sha256": local_sha,
        "local_asset": f"speak-epub-local-{lh}.zip",
    }


def write_split_files(requirements_text: str, out_dir: Path) -> tuple[Path, Path]:
    """Write the two pip requirement files the CI installs from."""
    core, local = split_requirements(requirements_text)
    out_dir.mkdir(parents=True, exist_ok=True)
    core_path = out_dir / "requirements-core.txt"
    local_path = out_dir / "requirements-local.txt"
    core_path.write_text("\n".join(core) + "\n", encoding="utf-8")
    local_path.write_text("\n".join(local) + "\n", encoding="utf-8")
    return core_path, local_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-version", required=True, help="exact interpreter build, e.g. 3.11.17+20261013")
    parser.add_argument("--requirements", default="requirements.txt")
    parser.add_argument("--out", required=True, help="path of the runtime.json to write")
    parser.add_argument("--release-url", default=None, help="release download base URL (with the tag)")
    parser.add_argument("--split-out-dir", default=None, help="where to write the split requirement files")
    args = parser.parse_args(argv)

    req_path = Path(args.requirements)
    text = req_path.read_text(encoding="utf-8") if req_path.is_file() else ""
    descriptor = build_descriptor(args.python_version, text, args.release_url)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(descriptor, indent=2) + "\n", encoding="utf-8")
    print(f"runtime {descriptor['hash']} -> {out} (asset {descriptor['asset']})")
    print(f"local   {descriptor['local_hash']} (asset {descriptor['local_asset']})")
    if args.split_out_dir:
        core_path, local_path = write_split_files(text, Path(args.split_out_dir))
        print(f"split requirements: {core_path} {local_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
