#!/usr/bin/env python3
"""Build the self-contained CLI package (speak.py + code + runtime descriptor).

The package is tiny (~0.2 MB): on the first run it downloads the Python
runtime tier (the same release asset the desktop app uses) and caches it in
the user profile. `speak.cmd` / `speak.sh` also work on a machine without
any Python installed.
"""
from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: What goes into the package.
INCLUDE_DIRS = ("core", "adapters")
INCLUDE_FILES = ("speak.py",)


def build_package(out_zip: Path, descriptor: Path, version: str = "") -> Path:
    """Zip the CLI package; returns the archive path."""
    if not descriptor.is_file():
        raise SystemExit(f"runtime descriptor missing: {descriptor}")
    data = json.loads(descriptor.read_text(encoding="utf-8"))
    if not data.get("hash") or not data.get("asset"):
        raise SystemExit(f"runtime descriptor is incomplete: {descriptor}")

    out_zip.parent.mkdir(parents=True, exist_ok=True)
    if out_zip.exists():
        out_zip.unlink()
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in INCLUDE_FILES:
            path = ROOT / name
            if path.is_file():
                zf.write(path, name)
        for folder in INCLUDE_DIRS:
            base = ROOT / folder
            if not base.is_dir():
                continue
            for path in base.rglob("*"):
                if not path.is_file():
                    continue
                if "__pycache__" in path.parts or path.suffix == ".pyc":
                    continue
                zf.write(path, str(path.relative_to(ROOT)).replace("\\", "/"))
        zf.write(descriptor, "runtime.json")
        for launcher in ("scripts/speak.cmd", "scripts/speak.sh"):
            path = ROOT / launcher
            if path.is_file():
                zf.write(path, Path(launcher).name)
        readme = ROOT / "docs" / "CLI-PACKAGE.md"
        if readme.is_file():
            zf.write(readme, "README.md")
    return out_zip


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="path of the zip to write")
    parser.add_argument(
        "--descriptor",
        default=str(ROOT / "src-tauri" / "sidecar-runtime" / "runtime.json"),
        help="the runtime descriptor to ship",
    )
    parser.add_argument("--version", default="", help="version (for the file name)")
    args = parser.parse_args(argv)

    out = Path(args.out)
    build_package(out, Path(args.descriptor), args.version)
    size_mb = out.stat().st_size / (1024 * 1024)
    print(f"CLI package: {out} ({size_mb:.2f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
