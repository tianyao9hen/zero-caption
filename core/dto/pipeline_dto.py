"""完整 MVP 主链路 DTO。

这些对象属于核心层，用于表达桌面 UI 或命令行入口发起的完整处理请求。
它们只包含业务输入输出，不包含 Qt 控件或具体基础设施对象。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.dto.project_dto import CreateProjectResult
from core.dto.subtitle_dto import (
    TranscribeVideoResult,
    TranslateSubtitlesResult,
)
from core.dto.task_dto import ExportVideoResult


@dataclass(slots=True)
class ProcessVideoInput:
    """描述一次完整视频字幕处理请求。"""

    source_video: Path
    source_language: str
    target_language: str
    workspace_dir: Path
    context: str | None = None
    output_path: Path | None = None


@dataclass(slots=True)
class ProcessVideoResult:
    """汇总导入、识别、翻译和导出四个用例的结果。"""

    project: CreateProjectResult
    transcription: TranscribeVideoResult
    translation: TranslateSubtitlesResult
    export: ExportVideoResult
