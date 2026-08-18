"""已有项目重新导出用例。

本模块位于核心层，负责从结构化字幕重建正式字幕文件，再调用现有视频
导出用例。它不依赖 Qt、SQLite 或具体 `FFmpeg` 实现。
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from core.domain.enums import ExportMode
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
    """使用项目当前保存的完整译文重新生成下载成品。

    单句编辑会先更新结构化字幕仓储。重新导出时从仓储重新写出 `SRT`，
    可以确保下载结果采用最新译文，而不是误用上一次导出时复制的旧字幕。
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

        # 第三步：优先采用本次显式路径，其次按当前模式复用项目上次路径，
        # 最后回退到项目 `exports/`。模式切换时要修正扩展名，避免之前下载
        # 外挂字幕留下的 `.srt` 被误当成烧录视频输出路径。
        output_path = self._resolve_output_path(project, request)
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

    @staticmethod
    def _resolve_output_path(
        project,
        request: ReexportProjectInput,
    ):
        """按导出模式选择一个不会混淆视频和字幕的默认路径。"""

        if request.output_path is not None:
            return request.output_path

        previous_path = project.output_path
        if previous_path is not None:
            if request.mode is ExportMode.SOFT_SUBTITLE:
                return previous_path.with_suffix(".srt")
            if previous_path.suffix.lower() == ".srt":
                return previous_path.with_suffix(
                    project.source_video.suffix or ".mp4"
                )
            return previous_path

        if request.mode is ExportMode.SOFT_SUBTITLE:
            return (
                project.workspace_dir
                / "exports"
                / f"{project.source_video.stem}-字幕.srt"
            )
        return project.workspace_dir / "exports" / project.source_video.name
