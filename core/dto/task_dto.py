"""任务与导出相关 DTO 模块。

阶段 1 先把任务摘要和导出请求/结果稳定下来，
这样 `TaskService`、用例和后续导出适配器可以共享同一套数据结构。
"""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(slots=True)
class ExportVideoInput:
    """描述导出用例和导出端口共用的输入参数。"""

    project_id: str
    source_video: Path
    subtitle_path: Path
    output_path: Path
    mode: ExportMode


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
