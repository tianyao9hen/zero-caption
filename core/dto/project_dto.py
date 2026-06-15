"""项目相关 DTO 模块。

这个文件属于 `core/dto`，负责定义跨层传输的项目输入输出结构。
DTO 只表达数据，不负责业务决策，这样 `core/usecases` 和未来的 UI /
基础设施实现之间就可以通过稳定结构协作。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.domain.entities import Project, Task


@dataclass(slots=True)
class CreateProjectInput:
    """描述创建项目用例所需的输入参数。"""

    source_video: Path
    source_language: str
    target_language: str
    workspace_dir: Path


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
