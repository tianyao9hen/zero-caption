"""任务与导出相关 DTO 模块。

阶段 1 先把任务摘要和导出请求/结果稳定下来，
这样 `TaskService`、用例和后续导出适配器可以共享同一套数据结构。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core.domain.entities import Project, Task
from core.domain.enums import ExportMode


@dataclass(slots=True)
class TaskSummaryDTO:
    """表示给界面层或日志层使用的任务摘要。"""

    task_id: str
    task_type: str
    status: str
    progress: int
    current_step: str
    message: str
    project_id: str = ""


@dataclass(slots=True)
class VideoTaskHistoryDTO:
    """表示任务页中一条持久化的视频处理记录。

    一个视频项目会依次产生导入、识别、翻译和导出等多个内部任务。
    界面不直接展示这些实现细节，而是把同一项目聚合成一个视频任务条目，
    并附带最近内部任务的状态，便于用户按视频理解处理进度。
    """

    project_id: str
    display_name: str
    source_video: Path
    workspace_dir: Path
    output_path: Path | None
    source_language: str
    target_language: str
    processing_mode: str
    export_mode: str
    project_status: str
    task_id: str
    task_type: str
    task_status: str
    progress: int
    checkpoint: str
    current_step: str
    message: str
    error_message: str
    retry_count: int
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class ExportVideoInput:
    """描述导出用例和导出端口共用的输入参数。"""

    project_id: str
    source_video: Path
    subtitle_path: Path
    output_path: Path
    mode: ExportMode


@dataclass(slots=True)
class ReexportProjectInput:
    """描述用户使用当前字幕重新导出已有项目的请求。

    `output_path` 留空时继续使用项目上次保存的路径；如果项目从未导出，
    核心用例会回退到项目自己的 `exports/` 目录。
    """

    project_id: str
    mode: ExportMode
    output_path: Path | None = None


@dataclass(slots=True)
class ExportRecordDTO:
    """描述一次导出的结果记录。"""

    project_id: str
    source_video: Path
    subtitle_path: Path
    output_path: Path
    mode: ExportMode


@dataclass(slots=True)
class ExportVideoResult:
    """描述导出用例的输出结果。"""

    project: Project
    task: Task
    export_record: ExportRecordDTO
