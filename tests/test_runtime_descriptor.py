"""Tests for scripts/runtime_descriptor.py (the tier cache keys).

The hashes decide whether an app update re-downloads a tier, so they must
be stable for the same inputs and change when that tier's content changes.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.runtime_descriptor import (  # noqa: E402
    RUNTIME_FORMAT_VERSION,
    build_descriptor,
    local_hash,
    requirements_sha256,
    runtime_hash,
    split_requirements,
    write_split_files,
)

PY = "3.11.17+20261013"
REQ = (
    "# --- core ---\n"
    "requests==2.32.3\n"
    "beautifulsoup4==4.14.3\n"
    "\n"
    "# --- local ---\n"
    "numpy==2.4.6\n"
    "piper-tts==1.8.0\n"
)


class TestSplit:
    def test_splits_by_marker(self):
        core, local = split_requirements(REQ)
        assert core == ["requests==2.32.3", "beautifulsoup4==4.14.3"]
        assert local == ["numpy==2.4.6", "piper-tts==1.8.0"]

    def test_file_without_markers_is_core_only(self):
        core, local = split_requirements("requests==2.32.3\n")
        assert core == ["requests==2.32.3"]
        assert local == []

    def test_comments_and_blank_lines_are_ignored(self):
        core, local = split_requirements("# a comment\n\nrequests==1\n")
        assert core == ["requests==1"]
        assert local == []

    def test_write_split_files(self, tmp_path):
        core_path, local_path = write_split_files(REQ, tmp_path)
        assert "requests==2.32.3" in core_path.read_text(encoding="utf-8")
        assert "numpy==2.4.6" not in core_path.read_text(encoding="utf-8")
        assert "numpy==2.4.6" in local_path.read_text(encoding="utf-8")


class TestHashes:
    def test_runtime_hash_is_deterministic(self):
        assert runtime_hash(PY, "abc") == runtime_hash(PY, "abc")
        assert build_descriptor(PY, REQ) == build_descriptor(PY, REQ)

    def test_runtime_hash_changes_with_the_interpreter(self):
        assert runtime_hash(PY, "abc") != runtime_hash("3.12.1+x", "abc")

    def test_runtime_hash_ignores_the_local_dependencies(self):
        """The runtime tier must NOT change when only Piper changes."""
        a = build_descriptor(PY, REQ)
        b = build_descriptor(PY, REQ.replace("numpy==2.4.6", "numpy==2.5.0"))
        assert a["hash"] == b["hash"]
        assert a["local_hash"] != b["local_hash"]

    def test_local_hash_changes_with_the_local_dependencies(self):
        a = build_descriptor(PY, REQ)
        b = build_descriptor(PY, REQ.replace("piper-tts==1.8.0", "piper-tts==1.9.0"))
        assert a["local_hash"] != b["local_hash"]
        assert a["hash"] == b["hash"]

    def test_requirements_digest_is_order_insensitive(self):
        assert requirements_sha256(["a==1", "b==2"]) == requirements_sha256(["b==2", "a==1"])

    def test_local_hash_is_stable(self):
        assert local_hash("abc") == local_hash("abc")


class TestDescriptor:
    def test_shape(self):
        d = build_descriptor(PY, REQ, "https://example.com/releases/download/v1.2.3")
        assert d["format"] == RUNTIME_FORMAT_VERSION
        assert len(d["hash"]) == 16 and len(d["local_hash"]) == 16
        assert d["asset"] == f"speak-epub-runtime-{d['hash']}.zip"
        assert d["local_asset"] == f"speak-epub-local-{d['local_hash']}.zip"
        assert d["python_version"] == PY
        assert d["release_url"] == "https://example.com/releases/download/v1.2.3"

    def test_default_release_url(self):
        d = build_descriptor(PY, REQ)
        assert "{version}" in d["release_url"] and "{asset}" in d["release_url"]

    def test_is_json_serialisable(self):
        payload = json.dumps(build_descriptor(PY, REQ))
        assert json.loads(payload)["hash"]
