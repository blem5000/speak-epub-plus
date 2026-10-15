"""Tests for Settings store — Story 4.2: Settings form + persist store.json + i18n."""
import json
from pathlib import Path

import pytest

from core.config import handle_rpc, load_store, DEFAULT_STORE


def _isolate(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def test_getStore_defaults(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    r = handle_rpc({"id": "1", "method": "getStore", "params": {}})
    assert "result" in r
    data = r["result"]
    # check defaults from DEFAULT_STORE
    assert data["voice"] == DEFAULT_STORE["voice"]
    assert data["rate"] == DEFAULT_STORE["rate"]
    assert data["parallel"] == DEFAULT_STORE["parallel"]
    assert data["chunk-size"] == DEFAULT_STORE["chunk-size"]
    assert data["retries"] == DEFAULT_STORE["retries"]
    assert data["scrapeDelay"] == DEFAULT_STORE["scrapeDelay"]
    assert data["safeMode"] == DEFAULT_STORE["safeMode"]
    assert data["keepEPUB"] == DEFAULT_STORE["keepEPUB"]
    assert data["keepMP3"] == DEFAULT_STORE["keepMP3"]
    assert data["keepM4B"] == DEFAULT_STORE["keepM4B"]


def test_setStore_voice_trim(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    r = handle_rpc({"id": "1", "method": "setStore", "params": {"voice": "  pl-PL-ZofiaNeural  "}})
    assert "result" in r
    assert r["result"]["voice"] == "pl-PL-ZofiaNeural"
    # reload
    r2 = handle_rpc({"id": "2", "method": "getStore", "params": {}})
    assert r2["result"]["voice"] == "pl-PL-ZofiaNeural"
    # file persisted
    data = json.loads((tmp_path / "store.json").read_text(encoding="utf-8"))
    assert data["voice"] == "pl-PL-ZofiaNeural"


def test_setStore_voice_invalid_empty(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    r = handle_rpc({"id": "1", "method": "setStore", "params": {"voice": "   "}})
    assert "error" in r
    assert r["error"]["code"] == "VALUE_ERROR"
    # voice too long truncated to 100 not error, but ensure still persists truncated
    long_voice = "a" * 150
    r2 = handle_rpc({"id": "2", "method": "setStore", "params": {"voice": long_voice}})
    assert "result" in r2
    assert len(r2["result"]["voice"]) == 100

    # non-string voice
    r3 = handle_rpc({"id": "3", "method": "setStore", "params": {"voice": 123}})
    assert "error" in r3
    assert r3["error"]["code"] == "VALUE_ERROR"


def test_setStore_rate_valid_and_clamp(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    # valid +10%
    r = handle_rpc({"id": "1", "method": "setStore", "params": {"rate": "+10%"}})
    assert "result" in r
    assert r["result"]["rate"] == "+10%"
    # valid -10%
    r2 = handle_rpc({"id": "2", "method": "setStore", "params": {"rate": "-10%"}})
    assert r2["result"]["rate"] == "-10%"
    # without plus should normalize to + prefix
    r3 = handle_rpc({"id": "3", "method": "setStore", "params": {"rate": "5%"}})
    assert r3["result"]["rate"] == "+5%"
    # clamp -150 -> -100
    r4 = handle_rpc({"id": "4", "method": "setStore", "params": {"rate": "-150%"}})
    assert r4["result"]["rate"] == "-100%"
    # clamp 150 -> +100%
    r5 = handle_rpc({"id": "5", "method": "setStore", "params": {"rate": "+150%"}})
    assert r5["result"]["rate"] == "+100%"
    # 0 -> +0%
    r6 = handle_rpc({"id": "6", "method": "setStore", "params": {"rate": "0%"}})
    assert r6["result"]["rate"] == "+0%"


def test_setStore_rate_invalid_reject(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    # missing %
    r = handle_rpc({"id": "1", "method": "setStore", "params": {"rate": "+10"}})
    assert "error" in r
    assert r["error"]["code"] == "VALUE_ERROR"
    # invalid pattern
    r2 = handle_rpc({"id": "2", "method": "setStore", "params": {"rate": "fast"}})
    assert "error" in r2
    # not string
    r3 = handle_rpc({"id": "3", "method": "setStore", "params": {"rate": 10}})
    assert "error" in r3
    # ensure not persisted after error: getStore still default
    r4 = handle_rpc({"id": "4", "method": "getStore", "params": {}})
    assert r4["result"]["rate"] == DEFAULT_STORE["rate"]


def test_setStore_parallel_clamp(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    # valid 2
    r = handle_rpc({"id": "1", "method": "setStore", "params": {"parallel": 2}})
    assert r["result"]["parallel"] == 2
    # clamp 10 -> 6
    r2 = handle_rpc({"id": "2", "method": "setStore", "params": {"parallel": 10}})
    assert r2["result"]["parallel"] == 6
    # clamp 0 ->1
    r3 = handle_rpc({"id": "3", "method": "setStore", "params": {"parallel": 0}})
    assert r3["result"]["parallel"] == 1
    # string numeric
    r4 = handle_rpc({"id": "4", "method": "setStore", "params": {"parallel": "3"}})
    assert r4["result"]["parallel"] == 3
    # bool should be error (not int)
    r5 = handle_rpc({"id": "5", "method": "setStore", "params": {"parallel": True}})
    assert "error" in r5


def test_setStore_chunk_clamp(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    r = handle_rpc({"id": "1", "method": "setStore", "params": {"chunk-size": 10000}})
    assert r["result"]["chunk-size"] == 5000
    r2 = handle_rpc({"id": "2", "method": "setStore", "params": {"chunk_size": 100}})
    assert r2["result"]["chunk-size"] == 500
    # valid 3500
    r3 = handle_rpc({"id": "3", "method": "setStore", "params": {"chunk-size": 3500}})
    assert r3["result"]["chunk-size"] == 3500
    # snake variant persists canonical
    assert "chunk-size" in r2["result"]
    # ensure file has canonical key not snake
    data = json.loads((tmp_path / "store.json").read_text(encoding="utf-8"))
    assert "chunk-size" in data
    assert "chunk_size" not in data


def test_setStore_retries_clamp(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    r = handle_rpc({"id": "1", "method": "setStore", "params": {"retries": 20}})
    assert r["result"]["retries"] == 10
    r2 = handle_rpc({"id": "2", "method": "setStore", "params": {"retries": 0}})
    assert r2["result"]["retries"] == 1
    r3 = handle_rpc({"id": "3", "method": "setStore", "params": {"retries": 5}})
    assert r3["result"]["retries"] == 5


def test_setStore_scrapeDelay_clamp_and_variants(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    r = handle_rpc({"id": "1", "method": "setStore", "params": {"scrapeDelay": 7000}})
    assert r["result"]["scrapeDelay"] == 7000
    # snake variant
    r2 = handle_rpc({"id": "2", "method": "setStore", "params": {"scrape_delay": 3000}})
    assert r2["result"]["scrapeDelay"] == 3000
    # clamp negative
    r3 = handle_rpc({"id": "3", "method": "setStore", "params": {"scrapeDelay": -100}})
    assert r3["result"]["scrapeDelay"] == 0
    # clamp >20000
    r4 = handle_rpc({"id": "4", "method": "setStore", "params": {"scrapeDelay": 99999}})
    assert r4["result"]["scrapeDelay"] == 20000
    # ensure canonical in file
    data = json.loads((tmp_path / "store.json").read_text(encoding="utf-8"))
    assert "scrapeDelay" in data
    assert "scrape_delay" not in data


def test_setStore_safeMode_bool(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    r = handle_rpc({"id": "1", "method": "setStore", "params": {"safeMode": True}})
    assert r["result"]["safeMode"] is True
    r2 = handle_rpc({"id": "2", "method": "setStore", "params": {"safeMode": False}})
    assert r2["result"]["safeMode"] is False
    # snake
    r3 = handle_rpc({"id": "3", "method": "setStore", "params": {"safe_mode": True}})
    assert r3["result"]["safeMode"] is True
    # string true
    r4 = handle_rpc({"id": "4", "method": "setStore", "params": {"safeMode": "true"}})
    assert r4["result"]["safeMode"] is True
    r5 = handle_rpc({"id": "5", "method": "setStore", "params": {"safeMode": "false"}})
    assert r5["result"]["safeMode"] is False


def test_setStore_keep_bools(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    r = handle_rpc({"id": "1", "method": "setStore", "params": {"keepEPUB": False}})
    assert r["result"]["keepEPUB"] is False
    r2 = handle_rpc({"id": "2", "method": "setStore", "params": {"keepMP3": False, "keepM4B": True}})
    assert r2["result"]["keepMP3"] is False
    assert r2["result"]["keepM4B"] is True
    # ensure keepEPUB still persisted? previous patch merged
    r3 = handle_rpc({"id": "3", "method": "getStore", "params": {}})
    assert r3["result"]["keepEPUB"] is False
    assert r3["result"]["keepMP3"] is False


def test_setStore_audioBitrate_valid_variants_invalid(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    r = handle_rpc({"id": "1", "method": "setStore", "params": {"audioBitrate": "48k"}})
    assert r["result"]["audioBitrate"] == "48k"
    r2 = handle_rpc({"id": "2", "method": "setStore", "params": {"audio_bitrate": "64K"}})
    assert r2["result"]["audioBitrate"] == "64k"
    r3 = handle_rpc({"id": "3", "method": "setStore", "params": {"audioBitrate": "ogg"}})
    assert r3["error"]["code"] == "VALUE_ERROR"
    r4 = handle_rpc({"id": "4", "method": "setStore", "params": {"audioBitrate": "8k"}})
    assert r4["error"]["code"] == "VALUE_ERROR"
    r5 = handle_rpc({"id": "5", "method": "setStore", "params": {"audioBitrate": 48}})
    assert r5["error"]["code"] == "VALUE_ERROR"


def test_kebab_snake_normalization(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    # chunk_size should normalize to chunk-size
    handle_rpc({"id": "1", "method": "setStore", "params": {"chunk_size": 2000}})
    r = handle_rpc({"id": "2", "method": "getStore", "params": {}})
    assert r["result"]["chunk-size"] == 2000
    # scrape_delay to scrapeDelay
    handle_rpc({"id": "3", "method": "setStore", "params": {"scrape_delay": 5000}})
    r2 = handle_rpc({"id": "4", "method": "getStore", "params": {}})
    assert r2["result"]["scrapeDelay"] == 5000
    # safe_mode to safeMode
    handle_rpc({"id": "5", "method": "setStore", "params": {"safe_mode": True}})
    r3 = handle_rpc({"id": "6", "method": "getStore", "params": {}})
    assert r3["result"]["safeMode"] is True


def test_store_atomic_and_reload(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    # set via handle_rpc
    handle_rpc({"id": "1", "method": "setStore", "params": {"voice": "en-US-JennyNeural", "parallel": 2, "chunk-size": 2000}})
    # file exists and is valid json
    path = tmp_path / "store.json"
    assert path.exists()
    assert not (tmp_path / "store.json.tmp").exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["voice"] == "en-US-JennyNeural"
    assert data["parallel"] == 2
    assert data["chunk-size"] == 2000
    # load_store merges defaults
    from core.config import load_store

    loaded = load_store()
    assert loaded["voice"] == "en-US-JennyNeural"
    assert loaded["parallel"] == 2
    # subsequent patch merges
    handle_rpc({"id": "2", "method": "setStore", "params": {"retries": 7}})
    loaded2 = load_store()
    assert loaded2["voice"] == "en-US-JennyNeural"
    assert loaded2["retries"] == 7


def test_setStore_patch_non_dict_error(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    r = handle_rpc({"id": "1", "method": "setStore", "params": "not-a-dict"})
    assert "error" in r
    assert r["error"]["code"] == "VALUE_ERROR"


def test_setStore_unknown_key_passthrough(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    r = handle_rpc({"id": "1", "method": "setStore", "params": {"customKey": "customValue"}})
    assert "result" in r
    assert r["result"]["customKey"] == "customValue"


def test_setStore_update_keys(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    r = handle_rpc({"id": "1", "method": "getStore", "params": {}})
    assert r["result"]["updateAuto"] is True
    assert r["result"]["updateSkipped"] == ""
    r2 = handle_rpc({"id": "2", "method": "setStore", "params": {"updateAuto": False}})
    assert r2["result"]["updateAuto"] is False
    r3 = handle_rpc({"id": "3", "method": "setStore", "params": {"update_auto": "true"}})
    assert r3["result"]["updateAuto"] is True
    r4 = handle_rpc({"id": "4", "method": "setStore", "params": {"updateSkipped": "0.3.1"}})
    assert r4["result"]["updateSkipped"] == "0.3.1"
    r5 = handle_rpc({"id": "5", "method": "setStore", "params": {"update_skipped": " v1.2.3 "}})
    assert r5["result"]["updateSkipped"] == "v1.2.3"
    r6 = handle_rpc({"id": "6", "method": "setStore", "params": {"updateSkipped": 5}})
    assert r6["error"]["code"] == "VALUE_ERROR"
    # persistence roundtrip
    r7 = handle_rpc({"id": "7", "method": "getStore", "params": {}})
    assert r7["result"]["updateSkipped"] == "v1.2.3"
