"""外挂字幕导出适配器集成测试。

测试使用小型文本占位文件模拟视频和字幕，验证适配器只负责文件复制，
不把导出路径或文件系统细节泄露到核心用例。
"""

from __future__ import annotations

from core.domain.enums import ExportMode
from core.dto.task_dto import ExportVideoInput
from infrastructure.export.soft_subtitle_exporter import SoftSubtitleExporter


def test_soft_subtitle_exporter_copies_video_and_sidecar_subtitle(tmp_path) -> None:
    """外挂模式应生成目标视频和同名 `.srt` 旁车文件。"""

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

    # assert：两个正式产物内容都应与源文件一致，记录保存目标字幕路径。
    assert output_video.read_bytes() == b"fake video"
    assert output_video.with_suffix(".srt").read_text(encoding="utf-8") == "译文字幕"
    assert record.output_path == output_video
    assert record.subtitle_path == output_video.with_suffix(".srt")
