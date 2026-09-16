#!/usr/bin/env python
"""Verify spec 1.1 acceptance — run with venv python."""
import sys
from pathlib import Path

# Ensure repo root is on path (core/adapters live at root)
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))

import core.config as cfg
from core.ports import ScraperPort, Selectors
from adapters.novelphoenix import NovelPhoenixAdapter
from adapters.base import guess_adapter

print("=== get_venv_python OS-aware ===")
venv = cfg.get_venv_python()
print(f"  get_venv_python(): {venv}")
assert venv.endswith("Scripts\\python.exe") or venv.endswith("Scripts/python.exe"), "Windows path expected"
print("  PASS Windows path ends with Scripts/python.exe")
# Simulate posix
import os
orig = os.name
try:
    os.name = "posix"
    v_posix = cfg.get_venv_python()
    print(f"  posix simulated: {v_posix}")
    assert v_posix == "venv/bin/python"
    print("  PASS posix path")
finally:
    os.name = orig

print("\n=== ScraperPort ABC ===")
assert issubclass(NovelPhoenixAdapter, ScraperPort)
print("  PASS issubclass")

print("\n=== Adapter mock only ===")
a = NovelPhoenixAdapter()
for method, args in [
    ("search", ("title",)),
    ("listChapters", ("http://novelphoenix.com/novel/1",)),
    ("fetchChapter", ("http://novelphoenix.com/chapter/1",)),
]:
    try:
        getattr(a, method)(*args)
        print(f"  FAIL {method} should have raised")
        sys.exit(1)
    except NotImplementedError as e:
        assert "mock only — Epic 1.2 implements" in str(e), f"wrong message for {method}: {e}"
        print(f"  PASS {method} raises NotImplementedError: {e}")

print("\n=== getSelectors skeleton ===")
sel = a.getSelectors()
print(f"  selectors: {sel}")
assert isinstance(sel, Selectors)
assert sel.start is None and sel.end is None
print("  PASS Selectors(start=None, end=None)")

print("\n=== JSON-RPC handle_rpc ===")
for req, expected in [
    ({"id": "1", "method": "ping"}, "pong"),
    ({"id": "2", "method": "hello", "params": {"x": 1}}, {"echo": {"x": 1}, "pong": True}),
]:
    resp = cfg.handle_rpc(req)
    print(f"  req {req['method']} -> {resp}")
    assert resp["id"] == req["id"]
    assert "result" in resp
    if expected == "pong":
        assert resp["result"] == "pong"
    else:
        assert resp["result"] == expected
print("  PASS handle_rpc ping/hello")

print("\n=== store.json mirror ===")
# create temp store.json
store_path = Path("store.json")
orig_exists = store_path.exists()
orig_content = store_path.read_text(encoding="utf-8") if orig_exists else None
try:
    store_path.write_text('{"voice":"pl-PL-ZofiaNeural","parallel":3}', encoding="utf-8")
    data = cfg.load_store()
    print(f"  load_store: {data}")
    assert data["voice"] == "pl-PL-ZofiaNeural"
    assert data["parallel"] == 3
    # check default merging
    assert "chunk-size" in data
    print("  PASS load_store mirrors voice/parallel")
finally:
    if orig_exists:
        store_path.write_text(orig_content, encoding="utf-8")
    else:
        if store_path.exists():
            store_path.unlink()

print("\n=== guess_adapter fallback ===")
assert guess_adapter("https://novelphoenix.com/novel/test") == "novelphoenix"
assert guess_adapter("https://unknown.example.com/x") is None
print("  PASS guess_adapter")

print("\n=== All checks passed ===")
