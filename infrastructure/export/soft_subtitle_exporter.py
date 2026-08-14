"""外挂字幕导出适配器。

外挂字幕模式不会重新编码视频，只复制视频文件并把字幕复制到同名 `.srt`
旁车文件。这是 MVP 默认导出模式，速度快且保留字幕可编辑性。
"""

from __future__ import annotations

from pathlib import Path
import shutil

from core.domain.enums import ExportMode
from core.dto.task_dto import ExportRecordDTO, ExportVideoInput


class SoftSubtitleExporter:
    """复制源视频和字幕文件，生成外挂字幕导出结果。"""

    def export(self, request: ExportVideoInput) -> ExportRecordDTO:
        """执行外挂字幕导出并返回正式产物记录。

        参数：
            request：包含源视频、已生成字幕和目标视频路径的导出请求。

        副作用：
            创建目标目录并复制视频和字幕文件；不会修改源文件。
        """

        if request.mode is not ExportMode.SOFT_SUBTITLE:
            raise ValueError("外挂字幕导出器只支持 SOFT_SUBTITLE 模式。")
        if not request.source_video.is_file():
            raise FileNotFoundError(f"未找到源视频：{request.source_video}")
        if not request.subtitle_path.is_file():
            raise FileNotFoundError(f"未找到字幕文件：{request.subtitle_path}")

        output_path = request.output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        subtitle_output_path = output_path.with_suffix(".srt")

        # 先复制视频，再复制字幕旁车文件。
        # 两个产物都成功落盘后，核心用例才会把任务推进到“已导出”。
        shutil.copy2(request.source_video, output_path)
        shutil.copy2(request.subtitle_path, subtitle_output_path)

        return ExportRecordDTO(
            project_id=request.project_id,
            source_video=request.source_video,
            subtitle_path=subtitle_output_path,
            output_path=output_path,
            mode=request.mode,
        )
