"""任务状态页面。

页面只消费进度摘要 DTO。耗时工作运行在后台线程，
UI 线程通过主窗口定时器把进度快照转交给这里展示。
"""

from __future__ import annotations

from PySide6.QtWidgets import QFormLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from core.dto.task_dto import TaskSummaryDTO
from core.services.task_service import TaskService


class TasksPage(QWidget):
    """显示当前任务的步骤、进度和消息。"""

    def __init__(self, task_service: TaskService) -> None:
        super().__init__()
        self.task_id_label = QLabel("-")
        self.task_type_label = QLabel("-")
        self.status_label = QLabel("空闲")
        self.step_label = QLabel("-")
        self.message_label = QLabel("暂无任务")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        form = QFormLayout()
        form.addRow("任务编号", self.task_id_label)
        form.addRow("任务类型", self.task_type_label)
        form.addRow("状态", self.status_label)
        form.addRow("当前步骤", self.step_label)
        form.addRow("任务消息", self.message_label)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.progress_bar)
        layout.addStretch(1)

    def show_running(self) -> None:
        """在后台线程启动前把页面切换为运行中状态。"""

        self.status_label.setText("running")
        self.message_label.setText("任务已提交，等待后台处理")

    def update_summary(self, summary: TaskSummaryDTO) -> None:
        """用最新任务摘要刷新页面控件。"""

        self.task_id_label.setText(summary.task_id)
        self.task_type_label.setText(summary.task_type)
        self.status_label.setText(summary.status)
        self.step_label.setText(summary.current_step or "-")
        self.message_label.setText(summary.message or "-")
        self.progress_bar.setValue(summary.progress)
