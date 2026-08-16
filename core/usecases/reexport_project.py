"""已有项目重新导出用例。

本模块位于核心层，负责从结构化字幕重建正式字幕文件，再调用现有视频
导出用例。它不依赖 Qt、SQLite 或具体 `FFmpeg` 实现。
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from core.dto.task_dto import (
    ExportVideoInput,
    ExportVideoResult,
    ReexportProjectInput,
)
from core.ports.repository import ProjectRepository, SubtitleRepository
from core.ports.subtitle import SubtitleWriter
from core.usecases.export_video import ExportVideo


@dataclass(slots=True)
class ReexportProject:
    """使用项目当前保存的完整译文重新生成视频成品。

    单句编辑会先更新结构化字幕仓储。重新导出时从仓储重新写出 `SRT`，
    可以确保视频采用最新译文，而不是误用上一次导出时复制的旧旁车文件。
    """

    project_repository: ProjectRepository
    subtitle_repository: SubtitleRepository
    subtitle_writer: SubtitleWriter
    export_video: ExportVideo

    def execute(self, request: ReexportProjectInput) -> ExportVideoResult:
        """校验完整译文、重写字幕文件并执行一次视频导出。

        副作用：
            会重写项目级译文 `SRT`、更新项目保存的导出参数，并创建新的
            任务与导出记录。原始视频和音频始终留在本地。
        """

        project = self.project_repository.get_by_id(request.project_id)
        if project is None:
            raise ValueError(f"未找到项目：{request.project_id}")

        # 第一步：同时读取原文和译文，用稳定的字幕编号检查译文是否完整。
        # 只检查数量并不够，因为历史异常数据可能出现重复或错位编号。
        source_segments = self.subtitle_repository.get_source_segments(
            project.project_id
        )
        translated_segments = self.subtitle_repository.get_translated_segments(
            project.project_id,
            project.target_language,
        )
        translated_by_id = {
            segment.segment_id: segment for segment in translated_segments
        }
        if not source_segments or any(
            source.segment_id not in translated_by_id
            for source in source_segments
        ):
            raise ValueError("重新导出前必须先生成完整译文字幕。")
        ordered_segments = [
            translated_by_id[source.segment_id] for source in source_segments
        ]

        # 第二步：从结构化数据重写正式字幕，确保刚保存的人工修订会进入成品。
        language_name = self._safe_language_name(project.target_language)
        subtitle_path = (
            project.workspace_dir
            / "subtitles"
            / f"translated-{language_name}.srt"
        )
        subtitle_path = self.subtitle_writer.write_file(
            ordered_segments,
            subtitle_path,
        )

        # 第三步：优先采用本次显式路径，其次复用项目上次路径，最后回退到
        # 项目 `exports/`。导出参数先保存，即使外部导出失败也能再次重试。
        output_path = (
            request.output_path
            or project.output_path
            or project.workspace_dir / "exports" / project.source_video.name
        )
        project.export_mode = request.mode
        project.output_path = output_path
        project.touch()
        self.project_repository.save(project)

        return self.export_video.execute(
            ExportVideoInput(
                project_id=project.project_id,
                source_video=project.source_video,
                subtitle_path=subtitle_path,
                output_path=output_path,
                mode=request.mode,
            )
        )

    @staticmethod
    def _safe_language_name(language: str) -> str:
        """把语言代码转换成不会改变目录层级的文件名片段。"""

        safe_name = re.sub(r"[^0-9A-Za-z_-]+", "_", language).strip("_")
        return safe_name or "translated"
