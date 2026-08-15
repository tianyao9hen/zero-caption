"""任务状态页面。

页面只消费进度摘要 DTO。耗时工作运行在后台线程，
UI 线程通过主窗口定时器把进度快照转交给这里展示。
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from core.dto.subtitle_dto import TranslationProgressDTO
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
        self.translation_count_label = QLabel("尚未开始翻译")
        self.translation_preview = QPlainTextEdit()
        self.translation_preview.setObjectName("translationLivePreview")
        self.translation_preview.setReadOnly(True)
        self.translation_preview.setPlaceholderText(
            "逐句翻译开始后，原文和译文会实时追加到这里。"
        )
        self.translation_preview.document().setMaximumBlockCount(20_000)

        form = QFormLayout()
        form.addRow("任务编号", self.task_id_label)
        form.addRow("任务类型", self.task_type_label)
        form.addRow("状态", self.status_label)
        form.addRow("当前步骤", self.step_label)
        form.addRow("任务消息", self.message_label)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.progress_bar)
        translation_group = QGroupBox("逐句翻译实时结果")
        translation_layout = QVBoxLayout(translation_group)
        translation_layout.addWidget(self.translation_count_label)
        translation_layout.addWidget(self.translation_preview, 1)
        layout.addWidget(translation_group, 1)
        layout.addStretch(1)

    def show_running(self) -> None:
        """在后台线程启动前把页面切换为运行中状态。"""

        self.status_label.setText("running")
        self.message_label.setText("任务已提交，等待后台处理")
        self.translation_count_label.setText("等待字幕翻译")
        self.translation_preview.clear()

    def update_summary(self, summary: TaskSummaryDTO) -> None:
        """用最新任务摘要刷新页面控件。"""

        self.task_id_label.setText(summary.task_id)
        self.task_type_label.setText(summary.task_type)
        self.status_label.setText(summary.status)
        self.step_label.setText(summary.current_step or "-")
        self.message_label.setText(summary.message or "-")
        self.progress_bar.setValue(summary.progress)

    def update_translation_progress(self, progress: TranslationProgressDTO) -> None:
        """把后台刚完成的一条原文和译文追加到实时结果区。"""

        self.translation_count_label.setText(
            f"已完成 {progress.current_index}/{progress.total_segments} 条"
        )
        self.translation_preview.appendPlainText(
            "\n".join(
                [
                    f"[{progress.current_index}/{progress.total_segments}]",
                    f"原文：{progress.source_text}",
                    f"译文：{progress.translated_text}",
                    "",
                ]
            )
        )
        scroll_bar = self.translation_preview.verticalScrollBar()
        scroll_bar.setValue(scroll_bar.maximum())
