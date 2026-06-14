"""核心领域实体模块。

实体表示系统里最重要的业务对象。它们属于 core 层，
应该尽量避免掺入 UI 和基础设施细节。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .enums import ProjectStatus, TaskStatus


@dataclass(slots=True)
class Project:
    """表示应用正在跟踪的一个已导入视频项目。"""

    project_id: str
    source_video: Path
    status: ProjectStatus = ProjectStatus.NEW


@dataclass(slots=True)
class Task:
    """表示一个和项目关联的工作单元。"""

    task_id: str
    project_id: str
    status: TaskStatus = TaskStatus.PENDING

    # 当前进度先用整数百分比表示。
    # 后续如果需要更细的步骤级进度，可以在这里扩展结构。
    progress: int = 0

    # 当前状态消息先保留为短文本，已经足够给状态栏和任务页占位控件使用。
    message: str = ""
