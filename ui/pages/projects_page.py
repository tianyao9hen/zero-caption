"""项目页占位模块。

页面属于 UI 层，负责展示信息并把用户动作转发给服务层，
不应该自己持有业务流程逻辑。
"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

from core.services.task_service import TaskService
from infrastructure.storage.workspace import WorkspaceManager


class ProjectsPage(QWidget):
    """显示项目相关信息。"""

    def __init__(self, workspace: WorkspaceManager, task_service: TaskService) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("项目页占位"))

        # 在骨架阶段显示工作区路径很有用，因为它能直观看到未来项目数据会落到哪里。
        layout.addWidget(QLabel(f"Workspace: {workspace.root}"))
