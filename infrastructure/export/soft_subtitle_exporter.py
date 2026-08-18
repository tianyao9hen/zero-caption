"""外挂字幕导出适配器。

外挂字幕模式只把字幕文件复制到用户选择的位置。源视频仍然是本地输入，
不会因为用户下载外挂字幕而被再次复制或改名。
"""

from __future__ import annotations

from pathlib import Path
import shutil

from core.domain.enums import ExportMode
from core.dto.task_dto import ExportRecordDTO, ExportVideoInput


class SoftSubtitleExporter:
    """只复制字幕文件，生成外挂字幕下载结果。"""

    def export(self, request: ExportVideoInput) -> ExportRecordDTO:
        """执行外挂字幕导出并返回正式产物记录。

        参数：
            request：包含源视频、已生成字幕和用户选择的目标路径。

        副作用：
            创建目标目录并复制字幕文件；不会修改源视频或源字幕。
        """

        if request.mode is not ExportMode.SOFT_SUBTITLE:
            raise ValueError("外挂字幕导出器只支持 SOFT_SUBTITLE 模式。")
        if not request.source_video.is_file():
            raise FileNotFoundError(f"未找到源视频：{request.source_video}")
        if not request.subtitle_path.is_file():
            raise FileNotFoundError(f"未找到字幕文件：{request.subtitle_path}")

        # 旧调用方可能仍传入视频扩展名。这里统一把目标规整为 `.srt`，
        # 这样导出端口的行为不会因为 UI 或历史脚本遗漏扩展名而重新复制视频。
        subtitle_output_path = (
            request.output_path
            if request.output_path.suffix.lower() == ".srt"
            else request.output_path.with_suffix(".srt")
        )
        subtitle_output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(request.subtitle_path, subtitle_output_path)

        return ExportRecordDTO(
            project_id=request.project_id,
            source_video=request.source_video,
            subtitle_path=subtitle_output_path,
            output_path=subtitle_output_path,
            mode=request.mode,
        )
