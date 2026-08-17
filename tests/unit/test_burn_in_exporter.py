"""烧录导出测试，保护命令参数和失败信息。"""

import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from core.domain.enums import ExportMode
from core.dto.task_dto import ExportVideoInput
from infrastructure.export.burn_in_exporter import BurnInExporter


def test_burn_in_exporter_builds_ffmpeg_command(tmp_path, monkeypatch) -> None:
    """烧录模式应调用 FFmpeg 滤镜，并保留音频流。"""

    executable = tmp_path / "ffmpeg.exe"
    executable.write_bytes(b"fake")
    source = tmp_path / "source.mp4"
    subtitle = tmp_path / "subtitle.ass"
    output = tmp_path / "exports" / "output.mp4"
    source.write_bytes(b"video")
    subtitle.write_text("ass", encoding="utf-8")
    calls: list[list[str]] = []
    run_options: dict[str, object] = {}

    def fake_run(command, **kwargs):
        calls.append(command)
        run_options.update(kwargs)
        # 烧录器只有确认临时视频真实存在才会替换正式成品。
        # 测试在这里模拟 `FFmpeg` 写完该文件，而不启动外部进程。
        Path(command[-1]).write_bytes(b"burned video")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr("infrastructure.export.burn_in_exporter.subprocess.run", fake_run)
    record = BurnInExporter(executable).export(
        ExportVideoInput(
            project_id="project-1",
            source_video=source,
            subtitle_path=subtitle,
            output_path=output,
            mode=ExportMode.BURN_IN,
        )
    )

    assert record.mode is ExportMode.BURN_IN
    assert calls
    assert "-vf" in calls[0]
    assert "-c:a" in calls[0]
    assert "-nostdin" in calls[0]
    assert "-nostats" in calls[0]
    assert calls[0][-1].endswith(".mp4")
    assert calls[0][-1] != str(output)
    assert output.read_bytes() == b"burned video"
    assert not list(output.parent.glob("*.zero-caption-part.mp4"))
    expected_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    assert run_options["creationflags"] == expected_flags
    assert run_options["stdin"] is subprocess.DEVNULL
    assert run_options["encoding"] == "utf-8"
    assert run_options["errors"] == "replace"


def test_burn_in_exporter_preserves_existing_output_after_interruption(
    tmp_path,
    monkeypatch,
) -> None:
    """外部中断烧录时应保留旧成品，并清理本次生成的半成品。"""

    # arrange：重新导出的正式路径已经有一个可用视频，本次烧录随后中断。
    executable = tmp_path / "ffmpeg.exe"
    executable.write_bytes(b"fake")
    source = tmp_path / "source.mp4"
    subtitle = tmp_path / "subtitle.srt"
    output = tmp_path / "exports" / "output.mp4"
    source.write_bytes(b"source video")
    subtitle.write_text("字幕", encoding="utf-8")
    output.parent.mkdir(parents=True)
    output.write_bytes(b"previous complete video")

    def interrupted_run(command, **_kwargs):
        Path(command[-1]).write_bytes(b"incomplete video")
        noisy_progress = "\n".join(f"frame={index}" for index in range(100))
        return SimpleNamespace(
            returncode=255,
            stderr=f"{noisy_progress}\nExiting normally, received signal 15.",
            stdout="",
        )

    monkeypatch.setattr(
        "infrastructure.export.burn_in_exporter.subprocess.run",
        interrupted_run,
    )

    # act / assert：用户看到简短原因，磁盘上仍然是上一次完整成品。
    with pytest.raises(RuntimeError, match="烧录被外部中断"):
        BurnInExporter(executable).export(
            ExportVideoInput(
                project_id="project-1",
                source_video=source,
                subtitle_path=subtitle,
                output_path=output,
                mode=ExportMode.BURN_IN,
            )
        )

    assert output.read_bytes() == b"previous complete video"
    assert not list(output.parent.glob("*.zero-caption-part.mp4"))
