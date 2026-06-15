"""ffprobe 适配器集成测试。"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from core.dto.media_dto import AudioStreamDTO, MediaProbeResultDTO, VideoStreamDTO
from infrastructure.media.ffprobe import FFprobeAdapter, FFprobeError


def test_ffprobe_adapter_reads_real_media_info():
    """应当能从真实视频样例中读出结构化媒体信息。"""

    adapter = FFprobeAdapter()
    result = adapter.probe(Path("tests/video/demo.mp4"))

    assert isinstance(result, MediaProbeResultDTO)
    assert result.source_path == Path("tests/video/demo.mp4")
    assert result.duration_ms > 0
    assert isinstance(result.video_stream, VideoStreamDTO)
    assert result.video_stream.width > 0
    assert result.video_stream.height > 0
    assert result.video_stream.codec_name
    assert result.audio_streams
    assert all(isinstance(item, AudioStreamDTO) for item in result.audio_streams)
    assert result.audio_streams[0].sample_rate > 0
    assert result.audio_streams[0].channels > 0
    assert result.audio_streams[0].codec_name


def test_ffprobe_adapter_prefers_bundled_executable():
    """应当优先使用随包内置的 ffprobe。"""

    adapter = FFprobeAdapter()
    bundled = Path("resources/bin/ffmpeg/ffprobe.exe").resolve()

    assert adapter.resolve_executable().resolve() == bundled


def test_ffprobe_adapter_raises_with_command_details(monkeypatch):
    """命令执行失败时应保留命令、退出码和错误输出。"""

    class _Completed:
        returncode = 1
        stdout = ""
        stderr = "boom"

    def fake_run(*args, **kwargs):
        return _Completed()

    monkeypatch.setattr(subprocess, "run", fake_run)

    adapter = FFprobeAdapter("ffprobe")

    with pytest.raises(FFprobeError) as exc_info:
        adapter.probe(Path("tests/video/demo.mp4"))

    assert exc_info.value.command[0] == str(Path("resources/bin/ffmpeg/ffprobe.exe").resolve())
    assert exc_info.value.returncode == 1
    assert exc_info.value.stderr == "boom"


def test_ffprobe_adapter_falls_back_to_path_when_bundle_missing():
    """随包文件缺失时，应回退到 PATH。"""

    adapter = FFprobeAdapter("ffprobe")

    with patch.object(FFprobeAdapter, "_bundle_candidates", return_value=[]), patch(
        "infrastructure.media.ffprobe.shutil.which", return_value="C:/tool/ffprobe.exe"
    ):
        assert adapter.resolve_executable() == Path("C:/tool/ffprobe.exe")
