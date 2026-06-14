"""简单状态栏控件模块。

这个控件会从 TaskService 读取摘要信息，并显示在主窗口底部。
"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel

from core.services.task_service import TaskService


class StatusBarWidget(QWidget):
    """显示当前任务状态的简短摘要。"""

    def __init__(self, task_service: TaskService) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        self.label = QLabel(task_service.summary())
        layout.addWidget(self.label)
        layout.addStretch(1)
