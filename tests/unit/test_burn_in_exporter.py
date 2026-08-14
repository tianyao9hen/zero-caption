"""烧录导出测试，保护命令参数和失败信息。"""

from types import SimpleNamespace

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

    def fake_run(command, **_kwargs):
        calls.append(command)
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
    assert str(output) == calls[0][-1]
