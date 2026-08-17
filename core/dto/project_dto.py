"""项目相关 DTO 模块。

这个文件属于 `core/dto`，负责定义跨层传输的项目输入输出结构。
DTO 只表达数据，不负责业务决策，这样 `core/usecases` 和未来的 UI /
基础设施实现之间就可以通过稳定结构协作。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.domain.entities import Project, Task
from core.domain.enums import ExportMode, ProcessingMode


@dataclass(slots=True)
class CreateProjectInput:
    """描述创建项目用例所需的输入参数。

    处理模式、翻译上下文和导出参数会随项目一起持久化，后续失败重试
    才能在应用重启后还原用户最初确认的请求，而不是依赖界面内存状态。
    `output_path` 保存仅识别任务的字幕路径；完整流程创建时应为空，等用户
    主动下载成品后再记录视频路径。它始终不代表内部缓存目录。
    """

    source_video: Path
    source_language: str
    target_language: str
    workspace_dir: Path
    translation_context: str = ""
    processing_mode: ProcessingMode = ProcessingMode.FULL_PIPELINE
    export_mode: ExportMode = ExportMode.SOFT_SUBTITLE
    output_path: Path | None = None


@dataclass(slots=True)
class ProjectSummaryDTO:
    """面向列表和摘要展示的项目快照。"""

    project_id: str
    source_video: Path
    source_language: str
    target_language: str
    workspace_dir: Path
    status: str
    last_error: str


@dataclass(slots=True)
class CreateProjectResult:
    """描述创建项目用例的返回结果。"""

    project: Project
    task: Task
