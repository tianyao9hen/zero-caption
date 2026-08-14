"""简单状态栏控件模块。

这个控件会从 TaskService 读取摘要信息，并显示在主窗口底部。
"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from core.dto.task_dto import TaskSummaryDTO
from core.services.task_service import TaskService


class StatusBarWidget(QWidget):
    """显示当前任务状态的简短摘要。"""

    def __init__(self, task_service: TaskService) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        self.label = QLabel(task_service.summary())
        layout.addWidget(self.label)
        layout.addStretch(1)

    def update_summary(self, summary: TaskSummaryDTO) -> None:
        """用最新任务摘要刷新状态栏文字。"""

        self.label.setText(
            f"{summary.task_type}: {summary.message} ({summary.progress}%)"
        )

    def show_message(self, message: str) -> None:
        """显示不属于单个任务摘要的应用级状态文字。"""

        self.label.setText(message)
