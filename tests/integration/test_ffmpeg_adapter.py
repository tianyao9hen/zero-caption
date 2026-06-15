"""FFmpeg 抽音频适配器集成测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from infrastructure.media.ffmpeg import FFmpegAdapter


@pytest.mark.parametrize(("suffix",), [(".wav",), (".flac",)])
def test_ffmpeg_adapter_extracts_audio_file_to_target_path(tmp_path, suffix: str):
    """应当可以把视频样例抽成指定格式的音频文件。"""

    source_path = Path("tests/video/demo.mp4")
    output_path = tmp_path / f"demo{suffix}"
    adapter = FFmpegAdapter()

    assert source_path.exists()

    result = adapter.extract_audio(source_path=source_path, output_path=output_path)

    assert result == output_path
    assert output_path.suffix == suffix
    assert output_path.exists()
