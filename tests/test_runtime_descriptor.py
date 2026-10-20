"""Tests for scripts/runtime_descriptor.py (the runtime-tier cache key).

The hash decides whether an app update re-downloads the Python runtime, so
it must be stable for the same inputs and change when the interpreter or
the dependency set changes.
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
    requirements_sha256,
    runtime_hash,
)

PY = "3.11.17+20261013"
REQ = "requests==2.32.3\nbeautifulsoup4==4.14.3\n"


class TestRuntimeDescriptor:
    def test_hash_is_deterministic(self):
        assert runtime_hash(PY, "abc") == runtime_hash(PY, "abc")
        assert build_descriptor(PY, REQ) == build_descriptor(PY, REQ)

    def test_hash_changes_with_the_interpreter(self):
        assert runtime_hash(PY, "abc") != runtime_hash("3.12.1+x", "abc")

    def test_hash_changes_with_the_dependencies(self):
        a = build_descriptor(PY, REQ)
        b = build_descriptor(PY, REQ + "lxml==6.0.2\n")
        assert a["hash"] != b["hash"]
        assert a["asset"] != b["asset"]

    def test_requirements_digest_ignores_comments_and_spacing(self):
        assert requirements_sha256("a==1\n\n# comment\nb==2\n") == requirements_sha256(
            "a==1\nb==2\n"
        )
        assert requirements_sha256("a==1\n") != requirements_sha256("a==2\n")

    def test_descriptor_shape(self):
        d = build_descriptor(PY, REQ)
        assert d["format"] == RUNTIME_FORMAT_VERSION
        assert len(d["hash"]) == 16
        assert d["asset"] == f"speak-epub-runtime-{d['hash']}.zip"
        assert d["python_version"] == PY
        assert "{version}" in d["url_template"] and "{asset}" in d["url_template"]

    def test_descriptor_is_json_serialisable(self):
        payload = json.dumps(build_descriptor(PY, REQ))
        assert json.loads(payload)["hash"]
