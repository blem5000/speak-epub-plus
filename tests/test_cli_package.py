"""Tests for the self-contained CLI package builder (scripts/make_cli_package.py)."""
import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from make_cli_package import build_package  # noqa: E402

DESCRIPTOR = {
    "format": 2,
    "hash": "abc123",
    "python_version": "3.11.17+20261013",
    "asset": "speak-epub-runtime-abc123.zip",
    "release_url": "https://github.com/owner/repo/releases/download/v1.2.3",
}


class TestCliPackage:
    def test_package_contains_the_cli(self, tmp_path):
        descriptor = tmp_path / "runtime.json"
        descriptor.write_text(json.dumps(DESCRIPTOR), encoding="utf-8")
        out = tmp_path / "cli.zip"
        build_package(out, descriptor)
        assert out.is_file()
        with zipfile.ZipFile(out) as zf:
            names = set(zf.namelist())
        assert "speak.py" in names
        assert "runtime.json" in names
        assert "speak.cmd" in names
        assert "speak.sh" in names
        assert "core/bootstrap.py" in names
        assert "core/config.py" in names
        assert "adapters/novelphoenix.py" in names
        assert "README.md" in names
        # no bytecode and no caches
        assert not any(n.endswith(".pyc") for n in names)
        assert not any("__pycache__" in n for n in names)

    def test_package_is_small(self, tmp_path):
        descriptor = tmp_path / "runtime.json"
        descriptor.write_text(json.dumps(DESCRIPTOR), encoding="utf-8")
        out = tmp_path / "cli.zip"
        build_package(out, descriptor)
        assert out.stat().st_size < 2 * 1024 * 1024  # under 2 MB

    def test_incomplete_descriptor_is_rejected(self, tmp_path):
        descriptor = tmp_path / "runtime.json"
        descriptor.write_text(json.dumps({"format": 2}), encoding="utf-8")
        with pytest.raises(SystemExit):
            build_package(tmp_path / "cli.zip", descriptor)
