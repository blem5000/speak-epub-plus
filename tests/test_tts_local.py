"""Tests for core/tts_local.py — Piper engine plumbing (no piper/network needed)."""
import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core.tts_local as tts_local  # noqa: E402
from core.tts_local import (  # noqa: E402
    DEFAULT_LOCAL_VOICE,
    LOCAL_MIN_CORES,
    LOCAL_VOICES,
    download_local_voice,
    effective_local_parallel,
    list_local_voices,
    local_voice_ready,
    rate_to_length_scale,
    resolve_engine,
    tts_text_to_mp3_local,
    validate_local_voice,
)


@pytest.fixture(autouse=True)
def _models_dir(tmp_path, monkeypatch):
    models = tmp_path / "models"
    monkeypatch.setenv("SPEAK_EPUB_MODELS_DIR", str(models))
    monkeypatch.setattr(tts_local, "_piper_available", lambda: True)
    tts_local._VOICE_CACHE.clear()
    return models


def _fake_model(models_dir: Path, voice: str) -> None:
    models_dir.mkdir(parents=True, exist_ok=True)
    (models_dir / f"{voice}.onnx").write_bytes(b"0" * 1_100_000)
    (models_dir / f"{voice}.onnx.json").write_text("{}", encoding="utf-8")


# ---------------------------------------------------------------------------
# rate → length_scale mapping
# ---------------------------------------------------------------------------

def test_rate_to_length_scale_matrix():
    assert rate_to_length_scale("+0%") == pytest.approx(1.0)
    assert rate_to_length_scale("+25%") == pytest.approx(0.8)
    assert rate_to_length_scale("+100%") == pytest.approx(0.5)
    assert rate_to_length_scale("-25%") == pytest.approx(1.0 / 0.75)
    # slowest allowed: speed 0.75 (duration checks keep their margin)
    assert rate_to_length_scale("-100%") == pytest.approx(1.0 / 0.75)
    assert rate_to_length_scale(None) == pytest.approx(1.0)
    assert rate_to_length_scale("garbage") == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# validation / status
# ---------------------------------------------------------------------------

def test_validate_local_voice():
    assert validate_local_voice("pl_PL-darkman-medium") == "pl_PL-darkman-medium"
    with pytest.raises(ValueError):
        validate_local_voice("xx_XX-evil-voice")
    with pytest.raises(ValueError):
        validate_local_voice(None)


def test_local_voice_ready_requires_files(tmp_path):
    assert not local_voice_ready("pl_PL-darkman-medium")
    _fake_model(Path(tts_local.local_models_root()), "pl_PL-darkman-medium")
    assert local_voice_ready("pl_PL-darkman-medium")
    # unknown voices are never ready
    assert not local_voice_ready("xx_XX-evil-voice")


def test_local_voice_ready_false_when_piper_missing(monkeypatch):
    _fake_model(Path(tts_local.local_models_root()), "pl_PL-darkman-medium")
    monkeypatch.setattr(tts_local, "_piper_available", lambda: False)
    assert not local_voice_ready("pl_PL-darkman-medium")


def test_list_local_voices_status():
    result = list_local_voices()
    assert result["default"] == DEFAULT_LOCAL_VOICE
    assert result["piperAvailable"] is True
    ids = [v["id"] for v in result["voices"]]
    assert "pl_PL-darkman-medium" in ids
    assert all(v["downloaded"] is False for v in result["voices"])
    _fake_model(Path(tts_local.local_models_root()), "en_US-lessac-medium")
    result2 = list_local_voices()
    by_id = {v["id"]: v for v in result2["voices"]}
    assert by_id["en_US-lessac-medium"]["downloaded"] is True
    assert by_id["en_US-lessac-medium"]["bytes"] >= 1_100_000


# ---------------------------------------------------------------------------
# engine resolution (auto rules)
# ---------------------------------------------------------------------------

def test_resolve_engine_edge_always_wins():
    assert resolve_engine("edge") == "edge"
    assert resolve_engine("edge", "pl_PL-darkman-medium") == "edge"


def test_resolve_engine_local_requires_model():
    with pytest.raises(ValueError, match="not downloaded"):
        resolve_engine("local", "pl_PL-darkman-medium")
    _fake_model(Path(tts_local.local_models_root()), "pl_PL-darkman-medium")
    assert resolve_engine("local", "pl_PL-darkman-medium") == "local"
    # empty voice -> default voice
    with pytest.raises(ValueError, match="not downloaded"):
        resolve_engine("local", "")
    # unknown voice names the voice, not the download state
    with pytest.raises(ValueError, match="unknown local voice"):
        resolve_engine("local", "xx_XX-evil-voice")


def test_resolve_engine_local_distinguishes_missing_piper(monkeypatch):
    _fake_model(Path(tts_local.local_models_root()), "pl_PL-darkman-medium")
    monkeypatch.setattr(tts_local, "_piper_available", lambda: False)
    with pytest.raises(ValueError, match="piper-tts is not installed"):
        resolve_engine("local", "pl_PL-darkman-medium")
    with pytest.raises(RuntimeError, match="piper-tts is not installed"):
        tts_text_to_mp3_local("hi", "/tmp/x.mp3", "pl_PL-darkman-medium")


def test_resolve_engine_auto_rules(monkeypatch):
    _fake_model(Path(tts_local.local_models_root()), "en_US-lessac-medium")
    monkeypatch.setattr(tts_local.os, "cpu_count", lambda: LOCAL_MIN_CORES + 4)
    assert resolve_engine("auto", "en_US-lessac-medium") == "local"
    monkeypatch.setattr(tts_local.os, "cpu_count", lambda: 4)
    assert resolve_engine("auto", "en_US-lessac-medium") == "edge"
    # fast CPU but model missing -> edge
    monkeypatch.setattr(tts_local.os, "cpu_count", lambda: LOCAL_MIN_CORES + 4)
    assert resolve_engine("auto", "pl_PL-gosia-medium") == "edge"


def test_effective_local_parallel(monkeypatch):
    monkeypatch.setattr(tts_local.os, "cpu_count", lambda: 32)
    assert effective_local_parallel() == tts_local.LOCAL_MAX_WORKERS
    monkeypatch.setattr(tts_local.os, "cpu_count", lambda: 2)
    assert effective_local_parallel() == 2
    monkeypatch.setattr(tts_local.os, "cpu_count", lambda: None)
    assert effective_local_parallel() >= 1


# ---------------------------------------------------------------------------
# download
# ---------------------------------------------------------------------------

def test_download_local_voice_uses_timeout_staging_urls(tmp_path):
    seen = {}

    class _FakeResp:
        def __init__(self, payload: bytes):
            self._payload = payload
            self.headers = {"Content-Length": str(len(payload))}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n=-1):
            chunk, self._payload = self._payload[:n], self._payload[n:]
            return chunk

    def fake_urlopen(req, timeout=None):
        seen["timeout"] = timeout
        seen.setdefault("urls", []).append(req.full_url)
        return _FakeResp(b"D" * 2_000_000)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = download_local_voice("pl_PL-darkman-medium")
    assert seen["timeout"] == tts_local._DOWNLOAD_TIMEOUT_SEC
    assert len(seen["urls"]) == 2  # model + config
    assert all("pl_PL-darkman-medium" in u for u in seen["urls"])
    assert Path(result["path"]).is_file()
    assert (Path(tts_local.local_models_root()) / "pl_PL-darkman-medium.onnx.json").is_file()
    # staging dir removed after atomic publish
    assert not list(Path(tts_local.local_models_root()).glob(".staging-*"))


def test_download_local_voice_rejects_unknown():
    with pytest.raises(ValueError):
        download_local_voice("xx_XX-evil-voice")


def test_download_local_voice_already_present_skips():
    _fake_model(Path(tts_local.local_models_root()), "pl_PL-darkman-medium")
    logs = []
    with patch("core.tts_local._fetch_to_file", side_effect=AssertionError("must not download")):
        download_local_voice("pl_PL-darkman-medium", on_log=logs.append)
    assert any("already downloaded" in line for line in logs)


def test_download_partial_failure_leaves_no_finals():
    def fake_fetch(url, dest_tmp, label, log_fn):
        Path(dest_tmp).write_bytes(b"partial")
        if dest_tmp.suffix == ".json":
            raise RuntimeError("connection reset")

    with patch("core.tts_local._fetch_to_file", side_effect=fake_fetch):
        with pytest.raises(RuntimeError, match="failed to download"):
            download_local_voice("pl_PL-darkman-medium")
    root = Path(tts_local.local_models_root())
    assert not (root / "pl_PL-darkman-medium.onnx").exists()
    assert not (root / "pl_PL-darkman-medium.onnx.json").exists()
    assert not list(root.glob(".staging-*"))


def test_download_force_redownloads_present_model():
    root = Path(tts_local.local_models_root())
    _fake_model(root, "pl_PL-darkman-medium")
    calls = []

    def fake_fetch(url, dest_tmp, label, log_fn):
        calls.append(url)
        Path(dest_tmp).write_bytes(b"N" * 1_100_000)

    with patch("core.tts_local._fetch_to_file", side_effect=fake_fetch):
        result = download_local_voice("pl_PL-darkman-medium", force=True)
    assert len(calls) == 2
    assert result["bytes"] == 1_100_000
    assert (root / "pl_PL-darkman-medium.onnx").read_bytes() == b"N" * 1_100_000


# ---------------------------------------------------------------------------
# synthesis (fake PiperVoice + fake ffmpeg)
# ---------------------------------------------------------------------------

class _FakePiperVoice:
    def __init__(self):
        self.texts = []

    @classmethod
    def load(cls, model_path):
        assert Path(model_path).is_file()
        return cls()

    def synthesize_wav(self, text, wav_file, syn_config=None):
        self.texts.append((text, syn_config))
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(22050)
        wav_file.writeframes(b"\x00\x00" * 22050)  # 1s of silence


def _fake_ffmpeg_run(cmd, capture_output=True, timeout=None):
    out = Path(cmd[-1])
    out.write_bytes(b"FAKEMP3" * 500)

    class _P:
        returncode = 0
        stderr = b""

    return _P()


def test_tts_text_to_mp3_local_happy_path(tmp_path):
    models = Path(tts_local.local_models_root())
    _fake_model(models, "pl_PL-darkman-medium")
    out = tmp_path / "part.mp3"
    fake_voice = _FakePiperVoice()

    with patch("piper.PiperVoice", create=True) as mock_cls:
        mock_cls.load.return_value = fake_voice
        with patch("core.tts_local.shutil.which", return_value="ffmpeg"):
            with patch("core.tts_local.subprocess.run", side_effect=_fake_ffmpeg_run):
                with patch("core.tts_local.verify_part_audio", return_value=(True, "ok")):
                    tts_text_to_mp3_local("hello world", str(out), "pl_PL-darkman-medium", rate="+25%")

    assert out.is_file()
    assert fake_voice.texts and fake_voice.texts[0][0] == "hello world"
    syn = fake_voice.texts[0][1]
    assert syn is not None and abs(syn.length_scale - 0.8) < 1e-6
    # temp wav cleaned up
    assert not list(tmp_path.glob("*.part.wav"))


def test_tts_text_to_mp3_local_requires_model(tmp_path):
    with pytest.raises(RuntimeError, match="not downloaded"):
        tts_text_to_mp3_local("hi", str(tmp_path / "x.mp3"), "pl_PL-darkman-medium")


def test_tts_text_to_mp3_local_requires_ffmpeg(tmp_path):
    models = Path(tts_local.local_models_root())
    _fake_model(models, "pl_PL-darkman-medium")

    with patch("piper.PiperVoice", create=True) as mock_cls:
        mock_cls.load.return_value = _FakePiperVoice()
        with patch("core.tts_local.shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="ffmpeg not found"):
                tts_text_to_mp3_local("hello", str(tmp_path / "y.mp3"), "pl_PL-darkman-medium")
    # failed run leaves no wav behind
    assert not list(tmp_path.glob("*.part.wav"))


def test_tts_text_to_mp3_local_invalid_output_cleaned(tmp_path):
    models = Path(tts_local.local_models_root())
    _fake_model(models, "pl_PL-darkman-medium")
    out = tmp_path / "bad.mp3"

    with patch("piper.PiperVoice", create=True) as mock_cls:
        mock_cls.load.return_value = _FakePiperVoice()
        with patch("core.tts_local.shutil.which", return_value="ffmpeg"):
            with patch("core.tts_local.subprocess.run", side_effect=_fake_ffmpeg_run):
                with patch("core.tts_local.verify_part_audio", return_value=(False, "truncated")):
                    with pytest.raises(RuntimeError, match="truncated"):
                        tts_text_to_mp3_local("hello", str(out), "pl_PL-darkman-medium")
    assert not out.exists()


def test_tts_text_to_mp3_local_transient_failure_retries_then_succeeds(tmp_path, monkeypatch):
    models = Path(tts_local.local_models_root())
    _fake_model(models, "pl_PL-darkman-medium")
    out = tmp_path / "retry.mp3"
    calls = {"n": 0}

    class _Flaky:
        @classmethod
        def load(cls, model_path):
            return cls()

        def synthesize_wav(self, text, wav_file, syn_config=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("flaky disk")
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(22050)
            wav_file.writeframes(b"\x00\x00" * 22050)

    retried = []
    monkeypatch.setattr(tts_local, "_load_voice", lambda name: _Flaky())
    monkeypatch.setattr(tts_local.time, "sleep", lambda s: None)
    with patch("core.tts_local.shutil.which", return_value="ffmpeg"):
        with patch("core.tts_local.subprocess.run", side_effect=_fake_ffmpeg_run):
            with patch("core.tts_local.verify_part_audio", return_value=(True, "ok")):
                tts_text_to_mp3_local("hello", str(out), "pl_PL-darkman-medium", retries=2,
                                      on_retry=lambda a, e: retried.append(a))
    assert out.is_file()
    assert calls["n"] == 2
    assert retried == [1]


def test_tts_text_to_mp3_local_retries_exhausted(tmp_path, monkeypatch):
    models = Path(tts_local.local_models_root())
    _fake_model(models, "pl_PL-darkman-medium")
    out = tmp_path / "fail.mp3"
    monkeypatch.setattr(tts_local.time, "sleep", lambda s: None)

    class _AlwaysBroken:
        @classmethod
        def load(cls, model_path):
            return cls()

        def synthesize_wav(self, text, wav_file, syn_config=None):
            # params set first: wave.close() must not mask the real failure
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(22050)
            raise RuntimeError("boom")

    monkeypatch.setattr(tts_local, "_load_voice", lambda name: _AlwaysBroken())
    with patch("core.tts_local.shutil.which", return_value="ffmpeg"):
        with pytest.raises(RuntimeError, match="failed after 1 attempt"):
            tts_text_to_mp3_local("hello", str(out), "pl_PL-darkman-medium", retries=1)
    assert not out.exists()


def test_tts_text_to_mp3_local_ffmpeg_failure_cleans_partial_mp3(tmp_path):
    models = Path(tts_local.local_models_root())
    _fake_model(models, "pl_PL-darkman-medium")
    out = tmp_path / "encodefail.mp3"
    captured = {}

    def _bad_ffmpeg(cmd, capture_output=True, timeout=None):
        captured["cmd"] = cmd
        out.write_bytes(b"TRUNCATED")
        class _P:
            returncode = 1
            stderr = b"encode error"
        return _P()

    with patch("piper.PiperVoice", create=True) as mock_cls:
        mock_cls.load.return_value = _FakePiperVoice()
        with patch("core.tts_local.shutil.which", return_value="ffmpeg"):
            with patch("core.tts_local.subprocess.run", side_effect=_bad_ffmpeg):
                with pytest.raises(RuntimeError, match="ffmpeg failed"):
                    tts_text_to_mp3_local("hello", str(out), "pl_PL-darkman-medium", retries=1)
    assert not out.exists()
    # canonical 24 kHz mono profile: mixed-engine chapters concat cleanly
    assert "-ar" in captured["cmd"] and "24000" in captured["cmd"]


# ---------------------------------------------------------------------------
# run_part_jobs integration (local branch)
# ---------------------------------------------------------------------------

def test_run_part_jobs_local_engine_uses_piper_pool(tmp_path, monkeypatch):
    from core.tts import PartJob, run_part_jobs

    models = Path(tts_local.local_models_root())
    _fake_model(models, "pl_PL-darkman-medium")
    monkeypatch.setattr(tts_local.os, "cpu_count", lambda: 32)

    jobs = [
        PartJob(
            chapter_number=1, chapter_title="T", part_number=i + 1, part_count=2,
            text=f"part {i}", output_path=str(tmp_path / f"p{i}.mp3"), is_final_chapter_file=(i == 1),
        )
        for i in range(2)
    ]
    seen = []

    def fake_local(text, output_path, voice, retries=5, rate=None):
        seen.append((text, voice, rate, retries))
        Path(output_path).write_bytes(b"MP3" * 500)

    logs = []

    async def _run():
        with patch("core.tts_local.tts_text_to_mp3_local", side_effect=fake_local):
            await run_part_jobs(
                jobs, voice="en-US-AndrewNeural", parallel=3, retries=5,
                rate="+10%", engine="local", local_voice="pl_PL-darkman-medium",
                on_log=logs.append, on_progress=lambda done, total: None,
            )

    asyncio.run(_run())
    assert sorted(s[0] for s in seen) == ["part 0", "part 1"]
    assert all(s[1] == "pl_PL-darkman-medium" for s in seen)
    assert all(s[2] == "+10%" for s in seen)
    assert any("local Piper pl_PL-darkman-medium" in line for line in logs)


def test_run_part_jobs_explicit_local_missing_model_raises(tmp_path):
    from core.tts import PartJob, run_part_jobs

    jobs = [
        PartJob(
            chapter_number=1, chapter_title="T", part_number=1, part_count=1,
            text="x", output_path=str(tmp_path / "p.mp3"), is_final_chapter_file=True,
        )
    ]

    async def _run():
        with pytest.raises(ValueError, match="not downloaded"):
            await run_part_jobs(jobs, voice="v", parallel=2, retries=2, engine="local")

    asyncio.run(_run())


def test_run_part_jobs_auto_falls_back_to_edge(tmp_path, monkeypatch):
    from core.tts import PartJob, run_part_jobs

    monkeypatch.setattr(tts_local.os, "cpu_count", lambda: 2)  # slow machine
    jobs = [
        PartJob(
            chapter_number=1, chapter_title="T", part_number=1, part_count=1,
            text="x", output_path=str(tmp_path / "p.mp3"), is_final_chapter_file=True,
        )
    ]
    calls = []

    async def fake_edge(text, output_path, voice, retries=5, rate=None):
        calls.append(voice)
        Path(output_path).write_bytes(b"MP3" * 500)

    logs = []

    async def _run():
        with patch("core.tts.tts_text_to_mp3", side_effect=fake_edge):
            await run_part_jobs(
                jobs, voice="en-US-AndrewNeural", parallel=2, retries=2,
                engine="auto", on_log=logs.append,
            )

    asyncio.run(_run())
    assert calls == ["en-US-AndrewNeural"]
    assert any("auto -> Edge TTS" in line for line in logs)
