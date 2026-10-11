"""任务与导出相关 DTO 模块。

阶段 1 先把任务摘要和导出请求/结果稳定下来，
这样 `TaskService`、用例和后续导出适配器可以共享同一套数据结构。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
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
    # 项目目录内已经烧录好的成品视频。为空表示这份成品还不能直接交付，
    # 用户下载时需要现场重新编码。字段放在最后并给出默认值，是为了兼容
    # 已经存在的旧调用方：它们不必为每个新短业务流程同步修改构造参数。
    prepared_output_path: Path | None = None


@dataclass(slots=True)
class ExportVideoInput:
    """描述导出用例和导出端口共用的输入参数。

    `output_path` 表示用户期望的主要成品路径。外挂模式最终会规整为
    `.srt` 字幕文件，烧录模式则保持为视频文件。

    `progress_callback` 是可选的进度上报入口。烧录需要重新编码整段视频，
    耗时可能达到数十分钟；适配器通过它回报已处理毫秒数和总毫秒数，
    用例才能把真实进度写进任务记录，而不是让界面停在 100% 空转。
    """

    project_id: str
    source_video: Path
    subtitle_path: Path
    output_path: Path
    mode: ExportMode
    # 已经烧录好的现成成品。非空时导出器直接把它复制到 `output_path`，
    # 不需要再读源视频重新编码，用户点击下载因此几乎不用等待。
    prepared_source_path: Path | None = None
    # 界面阶段文案标识。`export_video` 表示用户主动下载，
    # `prepare_product` 表示任务创建流程在项目目录内预生成同一份成品。
    task_type: str = "export_video"
    progress_callback: Callable[[int, int], None] | None = field(
        default=None,
        repr=False,
    )


@dataclass(slots=True)
class ReexportProjectInput:
    """描述用户使用当前字幕重新导出已有项目的请求。

    `output_path` 留空时继续使用项目上次保存的路径；如果项目从未导出，
    核心用例会回退到项目自己的 `exports/` 目录。

    `prepare_project_product` 为 `True` 时不是一次面向用户的下载，而是任务
    创建流程内部的“先把成品做好”动作：结果写入项目自己的 `exports/` 目录，
    并记录到 `Project.prepared_output_path`，不会覆盖用户上次选择的下载目录。
    """

    project_id: str
    mode: ExportMode
    output_path: Path | None = None
    prepare_project_product: bool = False


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
