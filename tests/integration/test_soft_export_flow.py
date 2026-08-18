"""外挂字幕导出适配器集成测试。

测试使用小型文本占位文件模拟视频和字幕，验证适配器只复制字幕文件，
不会因为用户选择外挂字幕而额外复制原视频。
"""

from __future__ import annotations

from core.domain.enums import ExportMode
from core.dto.task_dto import ExportVideoInput
from infrastructure.export.soft_subtitle_exporter import SoftSubtitleExporter


def test_soft_subtitle_exporter_only_copies_subtitle_file(tmp_path) -> None:
    """外挂模式应只生成目标 `.srt`，不复制原视频。"""

    # arrange
    source_video = tmp_path / "source.mp4"
    source_subtitle = tmp_path / "translated.srt"
    output_video = tmp_path / "exports" / "movie.mp4"
    source_video.write_bytes(b"fake video")
    source_subtitle.write_text("译文字幕", encoding="utf-8")
    request = ExportVideoInput(
        project_id="project-1",
        source_video=source_video,
        subtitle_path=source_subtitle,
        output_path=output_video,
        mode=ExportMode.SOFT_SUBTITLE,
    )

    # act
    record = SoftSubtitleExporter().export(request)

    # assert：旧调用方即使传入视频扩展名，也只会得到规整后的字幕文件。
    assert output_video.exists() is False
    assert output_video.with_suffix(".srt").read_text(encoding="utf-8") == "译文字幕"
    assert source_video.read_bytes() == b"fake video"
    assert record.output_path == output_video.with_suffix(".srt")
    assert record.subtitle_path == output_video.with_suffix(".srt")
