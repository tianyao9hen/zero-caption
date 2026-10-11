"""烧录导出测试，保护命令参数、进度上报和失败信息。"""

import io
import os
from pathlib import Path

import pytest

from core.domain.enums import ExportMode
from core.dto.task_dto import ExportVideoInput
from infrastructure.export.burn_in_exporter import BurnInExporter


class _FakePopen:
    """模拟一次 `FFmpeg` 子进程调用，避免单元测试真的启动外部程序。

    它提供适配器需要的最小接口：可迭代的 `stdout` / `stderr`、退出码，
    并在成功时把“已写出的临时成品”落到命令最后一个路径上。
    """

    def __init__(
        self,
        command,
        *,
        returncode: int = 0,
        stdout_text: str = "",
        stderr_text: str = "",
        **_options,
    ) -> None:
        self.command = list(command)
        self._returncode = returncode
        self.stdout = io.StringIO(stdout_text)
        self.stderr = io.StringIO(stderr_text)
        if returncode == 0:
            Path(command[-1]).write_bytes(b"burned video")

    def wait(self) -> int:
        """返回预设退出码，模拟等待子进程结束。"""

        return self._returncode

    @property
    def returncode(self) -> int:
        """返回进程退出码。"""

        return self._returncode


def _patch_duration_probe(monkeypatch, duration_ms: int = 0) -> None:
    """把时长探测固定为已知值，让断言只关注烧录命令本身。"""

    def fake_run(command, **_kwargs):
        text = (
            f"  Duration: 00:00:{duration_ms / 1000:06.3f}, start: 0.000000\n"
            if duration_ms
            else "  Duration: N/A, start: 0.000000\n"
        )
        return type("Result", (), {"returncode": 0, "stderr": text, "stdout": ""})()

    monkeypatch.setattr(
        "infrastructure.export.burn_in_exporter.subprocess.run",
        fake_run,
    )


def test_burn_in_exporter_builds_ffmpeg_command(tmp_path, monkeypatch) -> None:
    """烧录模式应调用 FFmpeg 滤镜，显式指定编码并保留进度上报。"""

    executable = tmp_path / "ffmpeg.exe"
    executable.write_bytes(b"fake")
    source = tmp_path / "source.mp4"
    subtitle = tmp_path / "subtitle.ass"
    output = tmp_path / "exports" / "output.mp4"
    source.write_bytes(b"video")
    subtitle.write_text("ass", encoding="utf-8")
    popen_options: dict[str, object] = {}
    calls: list[list[str]] = []

    def fake_popen(command, **kwargs):
        calls.append(list(command))
        popen_options.update(kwargs)
        return _FakePopen(command)

    _patch_duration_probe(monkeypatch)
    monkeypatch.setattr(
        "infrastructure.export.burn_in_exporter.subprocess.Popen",
        fake_popen,
    )
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
    # 进度上报依赖 `-progress`，因此这里不能再出现 `-nostats`。
    assert "-nostats" not in calls[0]
    assert "-progress" in calls[0]
    assert "libx264" in calls[0]
    assert calls[0][-1].endswith(".mp4")
    assert calls[0][-1] != str(output)
    assert output.read_bytes() == b"burned video"
    assert not list(output.parent.glob("*.zero-caption-part.mp4"))
    import subprocess

    expected_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    assert popen_options["creationflags"] == expected_flags
    assert popen_options["stdin"] is subprocess.DEVNULL
    assert popen_options["encoding"] == "utf-8"
    assert popen_options["errors"] == "replace"


def test_burn_in_exporter_reports_progress_from_ffmpeg_output(
    tmp_path,
    monkeypatch,
) -> None:
    """烧录应把 FFmpeg 的已处理时间回传给用例，用于展示真实进度。"""

    executable = tmp_path / "ffmpeg.exe"
    executable.write_bytes(b"fake")
    source = tmp_path / "source.mp4"
    subtitle = tmp_path / "subtitle.srt"
    output = tmp_path / "exports" / "output.mp4"
    source.write_bytes(b"video")
    subtitle.write_text("字幕", encoding="utf-8")
    reported: list[tuple[int, int]] = []
    progress_text = (
        "out_time_us=1000000\n"
        "out_time=00:00:01.000000\n"
        "frame=25\n"
        "out_time=00:00:03.500000\n"
        "progress=continue\n"
    )

    _patch_duration_probe(monkeypatch, duration_ms=10_000)
    monkeypatch.setattr(
        "infrastructure.export.burn_in_exporter.subprocess.Popen",
        lambda command, **_kwargs: _FakePopen(command, stdout_text=progress_text),
    )

    BurnInExporter(executable).export(
        ExportVideoInput(
            project_id="project-1",
            source_video=source,
            subtitle_path=subtitle,
            output_path=output,
            mode=ExportMode.BURN_IN,
            progress_callback=lambda done, total: reported.append((done, total)),
        )
    )

    assert reported == [(1_000, 10_000), (3_500, 10_000)]


def test_burn_in_exporter_retries_with_audio_encoding_when_copy_fails(
    tmp_path,
    monkeypatch,
) -> None:
    """音轨无法直接复制时，应改用通用音频编码再试一次。"""

    executable = tmp_path / "ffmpeg.exe"
    executable.write_bytes(b"fake")
    source = tmp_path / "source.mkv"
    subtitle = tmp_path / "subtitle.srt"
    output = tmp_path / "exports" / "output.mkv"
    source.write_bytes(b"video")
    subtitle.write_text("字幕", encoding="utf-8")
    commands: list[list[str]] = []
    outcomes = iter(
        [
            (1, "Could not find tag for codec aac in stream #1"),
            (0, ""),
        ]
    )

    def fake_popen(command, **_kwargs):
        commands.append(list(command))
        returncode, stderr_text = next(outcomes)
        return _FakePopen(
            command,
            returncode=returncode,
            stderr_text=stderr_text,
        )

    _patch_duration_probe(monkeypatch)
    monkeypatch.setattr(
        "infrastructure.export.burn_in_exporter.subprocess.Popen",
        fake_popen,
    )
    record = BurnInExporter(executable).export(
        ExportVideoInput(
            project_id="project-1",
            source_video=source,
            subtitle_path=subtitle,
            output_path=output,
            mode=ExportMode.BURN_IN,
        )
    )

    assert len(commands) == 2
    assert commands[0][commands[0].index("-c:a") + 1] == "copy"
    assert commands[1][commands[1].index("-c:a") + 1] == "aac"
    assert record.output_path == output


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

    def interrupted(command, **_kwargs):
        Path(command[-1]).write_bytes(b"incomplete video")
        noisy_progress = "\n".join(f"frame={index}" for index in range(100))
        return _FakePopen(
            command,
            returncode=255,
            stderr_text=f"{noisy_progress}\nExiting normally, received signal 15.",
        )

    _patch_duration_probe(monkeypatch)
    monkeypatch.setattr(
        "infrastructure.export.burn_in_exporter.subprocess.Popen",
        interrupted,
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


def test_burn_in_exporter_failure_message_drops_progress_noise(
    tmp_path,
    monkeypatch,
) -> None:
    """失败摘要里不应被 FFmpeg 的逐帧统计淹没。"""

    executable = tmp_path / "ffmpeg.exe"
    executable.write_bytes(b"fake")
    source = tmp_path / "source.mp4"
    subtitle = tmp_path / "subtitle.srt"
    output = tmp_path / "exports" / "output.mp4"
    source.write_bytes(b"video")
    subtitle.write_text("字幕", encoding="utf-8")
    noisy = "\n".join(
        [
            "frame=  100 fps=25 q=28.0 size=  1024kB time=00:00:04.00 bitrate=2097.1kbits/s speed=1.0x",
            "video:640x480 fps:25",
            "Conversion failed!",
        ]
    )

    _patch_duration_probe(monkeypatch)
    monkeypatch.setattr(
        "infrastructure.export.burn_in_exporter.subprocess.Popen",
        lambda command, **_kwargs: _FakePopen(
            command,
            returncode=1,
            stderr_text=noisy,
        ),
    )

    with pytest.raises(RuntimeError) as error:
        BurnInExporter(executable).export(
            ExportVideoInput(
                project_id="project-1",
                source_video=source,
                subtitle_path=subtitle,
                output_path=output,
                mode=ExportMode.BURN_IN,
            )
        )

    message = str(error.value)
    assert "Conversion failed!" in message
    assert "frame=" not in message
