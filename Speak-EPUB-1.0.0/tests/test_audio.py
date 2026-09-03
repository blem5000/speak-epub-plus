"""Tests for core/audio.py build_audio + buildAudio RPC (step 7: MP3/M4B/M4A).

TTS is faked (no network, no ffmpeg needed — single-part chapters skip merge).
"""
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PARENT = ROOT.parent
if str(PARENT) not in sys.path:
    sys.path.insert(0, str(PARENT))

from core.audio import build_audio
from core.config import handle_rpc
from core.fetch import write_cache
from core.ports import AdapterError


CH1 = "https://www.novelphoenix.com/novel/123/chapter/1"
CH2 = "https://www.novelphoenix.com/novel/123/chapter/2"


def _seed(tmp_path, url=CH1, title="Chapter 1", body="Short text one."):
    html = f"<html><body><h1>{title}</h1><div id='chapter-content'><p>{body}</p></div></body></html>"
    write_cache(url, html, cache_dir=tmp_path)
    return url


async def _fake_run(jobs, voice, parallel, retries, on_part_status=None, on_log=None, on_progress=None):
    for j in jobs:
        Path(j.output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(j.output_path).write_bytes(b"FAKEMP3" * 100)
        if on_part_status:
            on_part_status({"chapter_number": j.chapter_number, "part_number": j.part_number,
                            "part_count": j.part_count, "is_final_chapter_file": j.is_final_chapter_file,
                            "status": "done"})
    if on_progress:
        on_progress(len(jobs), len(jobs))


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
                build_audio("https://www.novelphoenix.com/novel/123", from_idx=1, to_idx=500,
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
