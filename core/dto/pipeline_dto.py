"""完整 MVP 主链路 DTO。

这些对象属于核心层，用于表达桌面 UI 或命令行入口发起的完整处理请求。
它们只包含业务输入输出，不包含 Qt 控件或具体基础设施对象。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.dto.project_dto import CreateProjectResult
from core.domain.entities import Project
from core.domain.enums import ExportMode, ProcessingMode
from core.dto.subtitle_dto import (
    TranscribeVideoResult,
    TranslateSubtitlesResult,
)
from core.dto.task_dto import ExportVideoResult


@dataclass(slots=True)
class ProcessVideoInput:
    """描述一次视频字幕处理请求。

    `processing_mode` 决定流程在原文字幕生成后结束，还是继续调用
    大模型翻译并导出视频。默认值保留原有完整流程语义，已有的命令行
    或测试调用方不会因为新增选项而静默改变行为。`output_path` 表示
    用户可见的主要成果：仅识别模式是 `.srt`，完整流程是视频文件。
    """

    source_video: Path
    source_language: str
    target_language: str
    workspace_dir: Path
    context: str | None = None
    output_path: Path | None = None
    export_mode: ExportMode = ExportMode.SOFT_SUBTITLE
    processing_mode: ProcessingMode = ProcessingMode.FULL_PIPELINE


@dataclass(slots=True)
class ProcessVideoResult:
    """汇总本次实际执行过的视频处理步骤。

    仅识别模式不会产生翻译和视频导出结果，因此后两个字段允许为空。
    调用方可以通过属性读取最终项目和本次最重要的字幕产物，
    不需要自己理解各个用例结果的嵌套结构。
    """

    project: CreateProjectResult
    transcription: TranscribeVideoResult
    translation: TranslateSubtitlesResult | None = None
    export: ExportVideoResult | None = None

    @property
    def final_project(self) -> Project:
        """返回流程结束时的项目快照。"""

        if self.export is not None:
            return self.export.project
        return self.project.project

    @property
    def subtitle_path(self) -> Path | None:
        """优先返回译文字幕，否则返回本地识别生成的原文字幕。"""

        if self.translation is not None:
            return self.translation.subtitle_path
        return self.transcription.subtitle_path
