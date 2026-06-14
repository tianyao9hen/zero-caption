"""任务页占位模块。"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

from core.services.task_service import TaskService


class TasksPage(QWidget):
    """显示后台任务状态的最小摘要。"""

    def __init__(self, task_service: TaskService) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("任务页占位"))
        layout.addWidget(QLabel(task_service.summary()))
