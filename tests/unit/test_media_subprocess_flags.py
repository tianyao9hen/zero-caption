"""媒体子进程窗口参数测试。

这些测试不启动真实 `FFmpeg`，只验证桌面应用传递了平台对应的创建标志，
防止 Windows 安装版处理任务时再次弹出黑色终端窗口。
"""

import json
import os
import subprocess
from types import SimpleNamespace

from infrastructure.media.ffmpeg import FFmpegAdapter
from infrastructure.media.ffprobe import FFprobeAdapter


def _expected_creation_flags() -> int:
    """返回当前平台创建后台媒体子进程时应使用的标志。"""

    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def test_ffmpeg_audio_extraction_uses_hidden_window_flags(
    tmp_path,
    monkeypatch,
) -> None:
    """音频抽取命令在 Windows 上应使用无窗口创建标志。"""

    executable = tmp_path / "ffmpeg.exe"
    executable.write_bytes(b"fake")
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr("infrastructure.media.ffmpeg.subprocess.run", fake_run)
    FFmpegAdapter(executable).extract_audio(
        tmp_path / "source.mp4",
        tmp_path / "source.wav",
    )

    assert captured["creationflags"] == _expected_creation_flags()


def test_ffprobe_uses_hidden_window_flags(tmp_path, monkeypatch) -> None:
    """媒体探测命令在 Windows 上应使用无窗口创建标志。"""

    executable = tmp_path / "ffprobe.exe"
    executable.write_bytes(b"fake")
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            returncode=0,
            stderr="",
            stdout=json.dumps({"format": {"duration": "0"}, "streams": []}),
        )

    monkeypatch.setattr("infrastructure.media.ffprobe.subprocess.run", fake_run)
    FFprobeAdapter(executable).probe(tmp_path / "source.mp4")

    assert captured["creationflags"] == _expected_creation_flags()
