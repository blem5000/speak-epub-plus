"""Tests for core/audio.py build_audio + buildAudio RPC (step 7: MP3/M4B/M4A).

TTS is faked (no network, no ffmpeg needed — single-part chapters skip merge).
"""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PARENT = ROOT.parent
if str(PARENT) not in sys.path:
    sys.path.insert(0, str(PARENT))

from core.audio import _filters_digest_for, build_audio
from core.config import handle_rpc
from core.fetch import write_cache
from core.ports import AdapterError


CH1 = "https://www.novelphoenix.com/novel/123/chapter/1"
CH2 = "https://www.novelphoenix.com/novel/123/chapter/2"


def _seed(tmp_path, url=CH1, title="Chapter 1", body="Short text one."):
    html = f"<html><body><h1>{title}</h1><div id='chapter-content'><p>{body}</p></div></body></html>"
    write_cache(url, html, cache_dir=tmp_path)
    return url


async def _fake_run(jobs, voice, parallel, retries, on_part_status=None, on_log=None, on_progress=None,
                    rate=None, adaptive=False, parallel_max=None, engine="edge", local_voice=None,
                    resume_lock=None):
    for j in jobs:
        Path(j.output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(j.output_path).write_bytes(b"FAKEMP3" * 100)
        if on_part_status:
            on_part_status({"chapter_number": j.chapter_number, "part_number": j.part_number,
                            "part_count": j.part_count, "is_final_chapter_file": j.is_final_chapter_file,
                            "status": "done"})
    if on_progress:
        on_progress(len(jobs), len(jobs))


def _bp_seed(tmp_path, url, num, story, subtitle):
    head = (
        f"<p>My House of Horrors-Chapter {num}</p><p>My House of Horrors</p>"
        f"<p>Chapter {num}</p><p>Restore scroll position</p>"
    )
    foot = (
        "<p>Translator: Lonelytree Editor: Millman97</p><p>Share to your friends</p>"
        f"<p>Chapter {num}</p><p>Report</p>"
    )
    html = (
        f"<html><body><div id='chapter-content'>{head}"
        f"<h2>Chapter {num}: {subtitle}</h2><p>{story}</p>{foot}</div></body></html>"
    )
    write_cache(url, html, cache_dir=tmp_path)


class TestBuildAudio:
    def test_mp3_two_chapters(self, tmp_path):
        _seed(tmp_path, CH1, "Chapter 1", "Short text one.")
        _seed(tmp_path, CH2, "Chapter 2", "Short text two.")
        with patch("core.audio.run_part_jobs", side_effect=_fake_run):
            res = build_audio(
                "https://www.novelphoenix.com/novel/123", from_idx=1, to_idx=2,
                title="Test Book", output_dir=tmp_path / "out", cache_dir=tmp_path,
                chapter_urls=[CH1, CH2], audio_format="mp3",
            )
        assert res["chapter_count"] == 2
        assert res["format"] == "mp3"
        assert res["audiobook"] is None
        assert len(res["chapters"]) == 2
        for ch in res["chapters"]:
            assert Path(ch["path"]).is_file()

    def test_cache_miss(self, tmp_path):
        try:
            with patch("core.audio.run_part_jobs", side_effect=_fake_run):
                build_audio("https://www.novelphoenix.com/novel/123", from_idx=1, to_idx=1,
                            output_dir=tmp_path / "out", cache_dir=tmp_path,
                            chapter_urls=[CH1], audio_format="mp3")
        except AdapterError as e:
            assert e.code == "CACHE_MISS"
        else:
            raise AssertionError("expected CACHE_MISS")

    def test_bad_format_and_range(self, tmp_path):
        _seed(tmp_path)
        try:
            with patch("core.audio.run_part_jobs", side_effect=_fake_run):
                build_audio("https://www.novelphoenix.com/novel/123", output_dir=tmp_path / "o",
                            cache_dir=tmp_path, chapter_urls=[CH1], audio_format="ogg")
        except ValueError as e:
            assert "format" in str(e)
        else:
            raise AssertionError("expected VALUE_ERROR")
        try:
            with patch("core.audio.run_part_jobs", side_effect=_fake_run):
                build_audio("https://www.novelphoenix.com/novel/123", from_idx=1, to_idx=501,
                            output_dir=tmp_path / "o", cache_dir=tmp_path, chapter_urls=[CH1])
        except ValueError as e:
            assert "too large" in str(e)
        else:
            raise AssertionError("expected range VALUE_ERROR")

    def test_bad_voice(self, tmp_path):
        _seed(tmp_path)
        try:
            with patch("core.audio.run_part_jobs", side_effect=_fake_run):
                build_audio("https://www.novelphoenix.com/novel/123", output_dir=tmp_path / "o",
                            cache_dir=tmp_path, chapter_urls=[CH1], voice="   ")
        except ValueError:
            pass
        else:
            raise AssertionError("expected VALUE_ERROR")

    def test_heartbeat_during_long_finalize(self, tmp_path, monkeypatch):
        import time

        import core.audio as audio_mod

        monkeypatch.setattr(audio_mod, "_HEARTBEAT_SEC", 0.2)
        _seed(tmp_path)
        handed_logs: list[str] = []

        def _slow_m4b(*args, **kwargs):
            time.sleep(1.0)

        def _on_log(line):
            handed_logs.append(line)

        with patch("core.audio.run_part_jobs", side_effect=_fake_run), patch(
            "core.audio.build_m4b", side_effect=_slow_m4b
        ):
            res = build_audio(
                "https://www.novelphoenix.com/novel/123", from_idx=1, to_idx=1,
                title="Test", output_dir=tmp_path / "out", cache_dir=tmp_path,
                chapter_urls=[CH1], audio_format="m4b", on_log=_on_log,
            )
        beats = [ln for ln in res["logs"] if ln.startswith("still working")]
        assert len(beats) >= 1, res["logs"]
        assert handed_logs and any("still working" in ln for ln in handed_logs)

    def test_boilerplate_stripped_from_tts_texts(self, tmp_path):
        _bp_seed(tmp_path, CH1, 57, "Chen Ge walked in slowly.", "She Has Arrived")
        _bp_seed(tmp_path, CH2, 58, "The mirror showed a woman.", "New Fools")
        seen_texts = []

        async def _capture(jobs, voice, parallel, retries, on_part_status=None, on_log=None, on_progress=None,
                           rate=None, adaptive=False, parallel_max=None, engine="edge", local_voice=None,
                           resume_lock=None):
            for j in jobs:
                seen_texts.append(j.text)
            await _fake_run(jobs, voice, parallel, retries, on_part_status, on_log, on_progress)

        with patch("core.audio.run_part_jobs", side_effect=_capture):
            res = build_audio(
                "https://www.novelphoenix.com/novel/123", from_idx=57, to_idx=58,
                title="Test", output_dir=tmp_path / "out", cache_dir=tmp_path,
                chapter_urls=[CH1, CH2], audio_format="mp3", auto_boilerplate=True,
            )
        assert res["chapter_count"] == 2
        joined = "\n".join(seen_texts)
        assert "Share to your friends" not in joined
        assert "Translator: Lonelytree" not in joined
        assert "Restore scroll position" not in joined
        assert "She Has Arrived" in joined
        assert "Chen Ge walked in slowly." in joined
        assert any("boilerplate templates" in ln for ln in res["logs"])


def test_merge_phase_events(tmp_path):
    from core.audio import build_audio as _build_audio

    _seed(tmp_path, CH1, "Chapter 1", "Short text one.")
    _seed(tmp_path, CH2, "Chapter 2", "Short text two.")
    phases: list = []
    with patch("core.audio.run_part_jobs", side_effect=_fake_run):
        _build_audio(
            "https://www.novelphoenix.com/novel/123", from_idx=1, to_idx=2,
            title="T", output_dir=tmp_path / "out", cache_dir=tmp_path,
            chapter_urls=[CH1, CH2], audio_format="mp3",
            on_phase=lambda p: phases.append(dict(p)),
        )
    merging = [p for p in phases if p.get("phase") == "merging"]
    assert [(p["done"], p["total"]) for p in merging] == [(1, 2), (2, 2)]


class TestBuildAudioWiring:
    """The build_audio -> tts wiring must be pinned (a silent regression here
    ships un-normalized audio, a missing cover or an ignored voice)."""

    def test_normalize_and_trim_reach_finalize(self, tmp_path):
        _seed(tmp_path, CH1, "Chapter 1", "Short text one.")
        seen = {}

        def _fake_finalize(plans, keep_parts, on_chapter=None, normalize_audio=False, trim_silence=False, on_log=None):
            seen["normalize"] = normalize_audio
            seen["trim"] = trim_silence
            return []

        with patch("core.audio.run_part_jobs", side_effect=_fake_run):
            with patch("core.audio.finalize_chapter_audio", side_effect=_fake_finalize):
                try:
                    build_audio(
                        "https://www.novelphoenix.com/novel/123", from_idx=1, to_idx=1,
                        title="T", output_dir=tmp_path / "out", cache_dir=tmp_path,
                        chapter_urls=[CH1], audio_format="mp3",
                        normalize_audio=True, trim_silence=True,
                    )
                except RuntimeError:
                    pass  # the fake finalize returns no audio
        assert seen.get("normalize") is True
        assert seen.get("trim") is True

    def test_build_manifest_written_into_audio_dir(self, tmp_path):
        _seed(tmp_path, CH1, "Chapter 1", "Short text one.")
        with patch("core.audio.run_part_jobs", side_effect=_fake_run):
            res = build_audio(
                "https://www.novelphoenix.com/novel/123", from_idx=1, to_idx=1,
                title="T", output_dir=tmp_path / "out", cache_dir=tmp_path,
                chapter_urls=[CH1], audio_format="mp3",
            )
        manifest = Path(res["audio_dir"]) / ".speak-epub-build.json"
        assert manifest.is_file()
        import json as _json

        stored = _json.loads(manifest.read_text(encoding="utf-8"))
        assert stored["source"] == "https://www.novelphoenix.com/novel/123"
        assert stored["chunk_size"] == 3500
        assert "filters" in stored and "auto_boilerplate" in stored

    def test_author_reaches_m4b_metadata(self, tmp_path):
        _seed(tmp_path, CH1, "Chapter 1", "Short text one.")
        captured = {}

        def _fake_m4b(output_dir, audio_entries, book_title, fmt, **kwargs):
            captured["artist"] = kwargs.get("artist")

        with patch("core.audio.run_part_jobs", side_effect=_fake_run):
            with patch("core.audio.build_m4b", side_effect=_fake_m4b):
                build_audio(
                    "https://www.novelphoenix.com/novel/123", from_idx=1, to_idx=1,
                    title="T", output_dir=tmp_path / "out", cache_dir=tmp_path,
                    chapter_urls=[CH1], audio_format="m4b", author="Jane Writer",
                )
        assert captured.get("artist") == "Jane Writer"

    def test_dialogue_voice_reaches_generation_plan(self, tmp_path):
        _seed(tmp_path, CH1, "Chapter 1", "Short text one.")
        captured = {}

        def _fake_plan(chapters, output_dir, chunk_size, rate=None, dialogue_voice=None, migrate_titles=False):
            captured["dialogue_voice"] = dialogue_voice
            return [], []

        with patch("core.audio.run_part_jobs", side_effect=_fake_run):
            with patch("core.audio.build_generation_plan", side_effect=_fake_plan):
                try:
                    build_audio(
                        "https://www.novelphoenix.com/novel/123", from_idx=1, to_idx=1,
                        title="T", output_dir=tmp_path / "out", cache_dir=tmp_path,
                        chapter_urls=[CH1], audio_format="mp3",
                        dialogue_voice="pl-PL-ZofiaNeural",
                    )
                except RuntimeError:
                    pass  # the stubbed plan produces no audio
        assert captured.get("dialogue_voice") == "pl-PL-ZofiaNeural"

    def test_filter_change_invalidates_previous_audio(self, tmp_path):
        _seed(tmp_path, CH1, "Chapter 1", "Short text one.")
        common = dict(
            title="T", output_dir=tmp_path / "out", cache_dir=tmp_path,
            chapter_urls=[CH1], audio_format="mp3",
        )
        with patch("core.audio.run_part_jobs", side_effect=_fake_run):
            res = build_audio("https://www.novelphoenix.com/novel/123", from_idx=1, to_idx=1, **common)
        manifest = Path(res["audio_dir"]) / ".speak-epub-build.json"
        import json as _json

        stored = _json.loads(manifest.read_text(encoding="utf-8"))
        assert stored["filters"] == _filters_digest_for([])

        # a changed filter set must change the identity -> regeneration
        assert _filters_digest_for([{"pattern": "xyz", "isRegex": False}]) != stored["filters"]

    def test_resume_lock_spans_the_whole_build(self, tmp_path):
        """The lock must be taken BEFORE the identity wipe and held through
        the merge/packaging — a second run must not wipe a running build."""
        _seed(tmp_path, CH1, "Chapter 1", "Short text one.")
        events = []
        lock = object()

        def _fake_acquire(root):
            events.append(("acquire", str(root)))
            return lock

        def _fake_release(lk):
            events.append(("release", lk is lock))

        async def _fake_run_with_lock(jobs, voice, parallel, retries, resume_lock=None, **kwargs):
            events.append(("jobs", resume_lock is lock))
            for j in jobs:
                Path(j.output_path).parent.mkdir(parents=True, exist_ok=True)
                Path(j.output_path).write_bytes(b"FAKEMP3" * 100)

        with patch("core.audio.acquire_resume_lock", side_effect=_fake_acquire):
            with patch("core.audio.release_resume_lock", side_effect=_fake_release):
                with patch("core.audio.run_part_jobs", side_effect=_fake_run_with_lock):
                    build_audio(
                        "https://www.novelphoenix.com/novel/123", from_idx=1, to_idx=1,
                        title="T", output_dir=tmp_path / "out", cache_dir=tmp_path,
                        chapter_urls=[CH1], audio_format="mp3",
                    )
        kinds = [e[0] for e in events]
        assert kinds[0] == "acquire", "the lock must be taken before anything else"
        assert ("jobs", True) in events, "the TTS run must run under the lock"
        assert kinds[-1] == "release", "the lock must be released at the end"
        assert events[-1][1] is True

    def test_concurrent_run_is_rejected(self, tmp_path):
        _seed(tmp_path, CH1, "Chapter 1", "Short text one.")

        def _boom(root):
            raise RuntimeError("concurrent resume detected")

        with patch("core.audio.acquire_resume_lock", side_effect=_boom):
            with pytest.raises(RuntimeError) as exc:
                build_audio(
                    "https://www.novelphoenix.com/novel/123", from_idx=1, to_idx=1,
                    title="T", output_dir=tmp_path / "out", cache_dir=tmp_path,
                    chapter_urls=[CH1], audio_format="mp3",
                )
        assert "concurrent resume" in str(exc.value)


class TestBuildAudioRpc:
    def test_rpc_validation(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        res = handle_rpc({"id": "1", "method": "buildAudio", "params": {"novelUrl": ""}})
        assert res["error"]["code"] == "VALUE_ERROR"
        res = handle_rpc({"id": "1", "method": "buildAudio", "params": {"novelUrl": "https://evil.com/x"}})
        assert res["error"]["code"] == "LIST_FAILED"

    def test_rpc_cache_miss_lists_missing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        res = handle_rpc({"id": "1", "method": "buildAudio", "params": {
            "novelUrl": "https://www.novelphoenix.com/novel/123",
            "urls": [CH1], "format": "mp3"}})
        assert res["error"]["code"] == "CACHE_MISS"
        assert res["error"]["missing"] == [CH1]

    def test_bitrate_result_and_invalid(self, tmp_path):
        _seed(tmp_path)
        with patch("core.audio.run_part_jobs", side_effect=_fake_run):
            res = build_audio(
                "https://www.novelphoenix.com/novel/123", from_idx=1, to_idx=1,
                title="T", output_dir=tmp_path / "out", cache_dir=tmp_path,
                chapter_urls=[CH1], audio_format="mp3", audio_bitrate="48k",
            )
        assert res["bitrate"] == "48k"
        try:
            with patch("core.audio.run_part_jobs", side_effect=_fake_run):
                build_audio(
                    "https://www.novelphoenix.com/novel/123", output_dir=tmp_path / "o2",
                    cache_dir=tmp_path, chapter_urls=[CH1], audio_bitrate="ogg",
                )
        except ValueError as e:
            assert "bitrate" in str(e)
        else:
            raise AssertionError("expected VALUE_ERROR")

    def test_rpc_bitrate_invalid(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _seed(tmp_path)
        res = handle_rpc({"id": "1", "method": "buildAudio", "params": {
            "novelUrl": "https://www.novelphoenix.com/novel/123",
            "urls": [CH1], "format": "mp3", "audioBitrate": "ogg"}})
        assert res["error"]["code"] == "VALUE_ERROR"

    def test_rate_forwarded_and_store_fallback(self, tmp_path, monkeypatch):
        _seed(tmp_path)
        captured = {}

        async def _capture(jobs, voice, parallel, retries, on_part_status=None, on_log=None,
                           on_progress=None, rate=None, adaptive=False, parallel_max=None,
                           engine="edge", local_voice=None, resume_lock=None):
            captured["rate"] = rate
            captured["adaptive"] = adaptive
            await _fake_run(jobs, voice, parallel, retries, on_part_status, on_log, on_progress)

        kwargs = dict(
            from_idx=1, to_idx=1, title="T", cache_dir=tmp_path,
            chapter_urls=[CH1], audio_format="mp3",
        )
        with patch("core.audio.run_part_jobs", side_effect=_capture):
            build_audio("https://www.novelphoenix.com/novel/123",
                        output_dir=tmp_path / "out_r1", rate="+35%", **kwargs)
        assert captured == {"rate": "+35%", "adaptive": True}

        # explicit None -> store-backed default
        monkeypatch.setattr("core.config.load_store", lambda: {"rate": "+20%"})
        with patch("core.audio.run_part_jobs", side_effect=_capture):
            build_audio("https://www.novelphoenix.com/novel/123",
                        output_dir=tmp_path / "out_r2", rate=None, **kwargs)
        assert captured["rate"] == "+20%"

        # garbage explicit rate is normalized to neutral, never crashes
        with patch("core.audio.run_part_jobs", side_effect=_capture):
            build_audio("https://www.novelphoenix.com/novel/123",
                        output_dir=tmp_path / "out_r3", rate="fast", **kwargs)
        assert captured["rate"] == "+0%"

    def test_rpc_rate_invalid_and_valid(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("core.fetch.CACHE_ROOT", tmp_path)
        _seed(tmp_path)
        res = handle_rpc({"id": "1", "method": "buildAudio", "params": {
            "novelUrl": "https://www.novelphoenix.com/novel/123",
            "urls": [CH1], "format": "mp3", "rate": "fast"}})
        assert res["error"]["code"] == "VALUE_ERROR"

        seen = {}

        def _fake_build_audio(**kw):
            seen.update(kw)
            return {"audio_dir": str(tmp_path / "out"), "chapters": []}

        monkeypatch.setattr("core.audio.build_audio", _fake_build_audio)
        res = handle_rpc({"id": "1", "method": "buildAudio", "params": {
            "novelUrl": "https://www.novelphoenix.com/novel/123",
            "urls": [CH1], "format": "mp3", "rate": "25"}})
        assert "error" not in res, res
        assert seen["rate"] == "+25%"  # normalized with an explicit sign

    def test_rpc_buildaudio_store_fallback_forwarding(self, tmp_path, monkeypatch):
        # review cr2: when buildAudio omits rate/engine, the Settings-persisted
        # store values must reach build_audio — the desktop UI's only binding.
        # Break the fallback (hardcode "+0%"/"auto") and this test must fail.
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("core.fetch.CACHE_ROOT", tmp_path)
        _seed(tmp_path)
        (tmp_path / "store.json").write_text('{"rate": "+20%", "engine": "edge"}', encoding="utf-8")
        seen = {}

        def _fake_build_audio(**kw):
            seen.update(kw)
            return {"audio_dir": str(tmp_path / "out"), "chapters": []}

        monkeypatch.setattr("core.audio.build_audio", _fake_build_audio)
        res = handle_rpc({"id": "1", "method": "buildAudio", "params": {
            "novelUrl": "https://www.novelphoenix.com/novel/123",
            "urls": [CH1], "format": "mp3"}})
        assert "error" not in res, res
        assert seen["rate"] == "+20%"
        assert seen["engine"] == "edge"

    def test_engine_forwarded_and_store_fallback(self, tmp_path, monkeypatch):
        # review cr2: isolate from the real store.json — the store fallback
        # reads it when local_voice is None, and a dev machine with a persisted
        # localVoice would otherwise fail the first assertion below
        monkeypatch.chdir(tmp_path)
        _seed(tmp_path)
        captured = {}

        async def _capture(jobs, voice, parallel, retries, on_part_status=None, on_log=None,
                           on_progress=None, rate=None, adaptive=False, parallel_max=None,
                           engine="edge", local_voice=None, resume_lock=None):
            captured["engine"] = engine
            captured["localVoice"] = local_voice
            await _fake_run(jobs, voice, parallel, retries, on_part_status, on_log, on_progress)

        kwargs = dict(
            from_idx=1, to_idx=1, title="T", cache_dir=tmp_path,
            chapter_urls=[CH1], audio_format="mp3",
        )
        with patch("core.audio.run_part_jobs", side_effect=_capture):
            build_audio("https://www.novelphoenix.com/novel/123",
                        output_dir=tmp_path / "out_e1", engine="edge", local_voice=None, **kwargs)
        assert captured == {"engine": "edge", "localVoice": None}

        monkeypatch.setattr("core.config.load_store",
                            lambda: {"engine": "local", "localVoice": "pl_PL-darkman-medium"})
        with patch("core.audio.run_part_jobs", side_effect=_capture):
            build_audio("https://www.novelphoenix.com/novel/123",
                        output_dir=tmp_path / "out_e2", engine=None, local_voice=None, **kwargs)
        assert captured == {"engine": "local", "localVoice": "pl_PL-darkman-medium"}

        # garbage engine normalizes to auto (never crashes the build)
        with patch("core.audio.run_part_jobs", side_effect=_capture):
            build_audio("https://www.novelphoenix.com/novel/123",
                        output_dir=tmp_path / "out_e3", engine="bogus", local_voice=None, **kwargs)
        assert captured["engine"] == "auto"

    def test_rpc_engine_validation(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("SPEAK_EPUB_MODELS_DIR", str(tmp_path / "models"))
        base = {"novelUrl": "https://www.novelphoenix.com/novel/123", "urls": [CH1], "format": "mp3"}

        res = handle_rpc({"id": "1", "method": "buildAudio", "params": {**base, "engine": "bogus"}})
        assert res["error"]["code"] == "VALUE_ERROR"
        assert "engine" in res["error"]["message"]

        res = handle_rpc({"id": "1", "method": "buildAudio",
                          "params": {**base, "engine": "local", "localVoice": "xx_XX-evil-voice"}})
        assert res["error"]["code"] == "VALUE_ERROR"
        assert "unknown local voice" in res["error"]["message"]

        res = handle_rpc({"id": "1", "method": "buildAudio",
                          "params": {**base, "engine": "local", "localVoice": "pl_PL-darkman-medium"}})
        assert res["error"]["code"] == "VALUE_ERROR"
        assert "not downloaded" in res["error"]["message"]

    def test_rpc_local_voices_and_download(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPEAK_EPUB_MODELS_DIR", str(tmp_path / "models"))
        res = handle_rpc({"id": "1", "method": "localVoices"})
        assert "error" not in res
        ids = [v["id"] for v in res["result"]["voices"]]
        assert "pl_PL-darkman-medium" in ids
        assert res["result"]["default"]

        res = handle_rpc({"id": "1", "method": "downloadLocalVoice", "params": {"voice": "nope"}})
        assert res["error"]["code"] == "VALUE_ERROR"

        def _fake_download(voice, on_log=None, force=False):
            if on_log:
                on_log(f"downloading {voice}...")
            return {"id": voice, "path": str(tmp_path / "models" / f"{voice}.onnx")}

        monkeypatch.setattr("core.tts_local.download_local_voice", _fake_download)
        events = []
        res = handle_rpc({"id": "1", "method": "downloadLocalVoice",
                          "params": {"voice": "pl_PL-darkman-medium"}},
                         emit_fn=lambda ev, payload: events.append((ev, payload)))
        assert "error" not in res
        assert res["result"]["id"] == "pl_PL-darkman-medium"
        # download progress reaches the UI through logLine events
        assert any(ev == "logLine" and "downloading pl_PL-darkman-medium" in str(pl)
                   for ev, pl in events)

        def _boom_download(voice, on_log=None, force=False):
            raise RuntimeError("network down")

        monkeypatch.setattr("core.tts_local.download_local_voice", _boom_download)
        res = handle_rpc({"id": "1", "method": "downloadLocalVoice",
                          "params": {"voice": "pl_PL-darkman-medium"}})
        assert res["error"]["code"] == "DOWNLOAD_FAILED"

    def test_rpc_download_force_flag_parsing(self, tmp_path, monkeypatch):
        # review cr2r: explicit force:false must not mask forceRedownload:true,
        # and the string "false" must not coerce to True
        monkeypatch.setenv("SPEAK_EPUB_MODELS_DIR", str(tmp_path / "models"))
        seen = {}

        def _force_download(voice, on_log=None, force=False):
            seen["force"] = force
            return {"id": voice, "path": "x"}

        monkeypatch.setattr("core.tts_local.download_local_voice", _force_download)
        base = {"voice": "pl_PL-darkman-medium"}
        res = handle_rpc({"id": "1", "method": "downloadLocalVoice",
                          "params": {**base, "force": False, "forceRedownload": True}})
        assert "error" not in res
        assert seen["force"] is True
        res = handle_rpc({"id": "1", "method": "downloadLocalVoice",
                          "params": {**base, "force": "false"}})
        assert "error" not in res
        assert seen["force"] is False
        res = handle_rpc({"id": "1", "method": "downloadLocalVoice",
                          "params": {**base, "force": "yes"}})
        assert "error" not in res
        assert seen["force"] is True

    def test_build_audio_ffmpeg_missing_warns_upfront(self, tmp_path, monkeypatch):
        # troubleshooter policy: know before hours of synthesis that merging
        # and truncation auto-repair are unavailable
        _seed(tmp_path)
        kwargs = dict(
            from_idx=1, to_idx=1, title="T", cache_dir=tmp_path,
            chapter_urls=[CH1], audio_format="mp3",
        )
        monkeypatch.setattr("core.audio.ffmpeg_available", lambda: False)
        with patch("core.audio.run_part_jobs", side_effect=_fake_run):
            res = build_audio("https://www.novelphoenix.com/novel/123",
                              output_dir=tmp_path / "out_ff", **kwargs)
        assert any("ffmpeg not found" in line for line in res["logs"])

    def test_build_audio_local_engine_requires_ffmpeg(self, tmp_path, monkeypatch):
        # local synthesis can never work without ffmpeg: fail fast, not on the
        # first part after minutes of queueing
        _seed(tmp_path)
        kwargs = dict(
            from_idx=1, to_idx=1, title="T", cache_dir=tmp_path,
            chapter_urls=[CH1], audio_format="mp3", engine="local",
            local_voice="pl_PL-darkman-medium",
        )
        monkeypatch.setattr("core.audio.ffmpeg_available", lambda: False)
        with patch("core.audio.run_part_jobs", side_effect=_fake_run):
            with pytest.raises(RuntimeError, match="requires ffmpeg"):
                build_audio("https://www.novelphoenix.com/novel/123",
                            output_dir=tmp_path / "out_ff2", **kwargs)

    def test_output_falls_back_when_cwd_unwritable(self, tmp_path, monkeypatch, capsys):
        """System32-CWD regression: default output lands in user docs, no WinError 5."""
        import os as _os

        monkeypatch.setattr("core.tts.user_output_base", lambda: tmp_path / "docs")
        fake_cwd = tmp_path / "System32"
        fake_cwd.mkdir()  # like the real System32: exists, but denied below
        real_mkdir = Path.mkdir
        real_writable = _os.access
        touched = []

        def _mkdir(self, *args, **kwargs):
            try:
                self.relative_to(fake_cwd)
            except ValueError:
                return real_mkdir(self, *args, **kwargs)
            touched.append(str(self))
            raise PermissionError(13, "Access is denied")

        def _writable(path):
            try:
                Path(path).relative_to(fake_cwd)
            except ValueError:
                return real_writable(path, _os.W_OK)
            return False

        monkeypatch.setattr(Path, "mkdir", _mkdir)
        monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: fake_cwd))
        monkeypatch.setattr("core.tts._is_writable", _writable)
        _seed(tmp_path)
        with patch("core.audio.run_part_jobs", side_effect=_fake_run):
            res = build_audio(
                "https://www.novelphoenix.com/novel/123", from_idx=1, to_idx=1,
                title="T", output_dir=None, cache_dir=tmp_path,
                chapter_urls=[CH1], audio_format="mp3",
            )
        fallback = (tmp_path / "docs" / "output").resolve()
        assert Path(res["audio_dir"]).resolve().parent == fallback
        for ch in res["chapters"]:
            assert Path(ch["path"]).is_file()
        assert touched == [], "denied CWD must be probed, never touched"
        assert "not usable" in capsys.readouterr().out
