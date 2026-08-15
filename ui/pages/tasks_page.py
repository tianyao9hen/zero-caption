"""视频任务工作区页面。

页面属于 UI 层，负责展示持久化的视频任务列表、当前任务详情和逐句译文。
历史数据通过 `TaskService` 查询，页面不直接访问 SQLite，也不执行媒体处理。
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from core.dto.subtitle_dto import TranslationProgressDTO
from core.dto.task_dto import TaskSummaryDTO, VideoTaskHistoryDTO
from core.services.task_service import TaskService


class TasksPage(QWidget):
    """按视频组织任务历史，并展示当前处理阶段和实时译文。"""

    # 页面只发出“用户想创建任务”的意图，主窗口负责打开参数对话框并
    # 创建后台线程。这样页面不会承担主流程编排职责。
    create_requested = Signal()

    _TASK_TYPE_LABELS = {
        "create_project": "导入视频",
        "transcribe_video": "生成字幕",
        "translate_subtitles": "逐句翻译",
        "export_video": "导出视频",
    }
    _STATUS_LABELS = {
        "new": "新建",
        "imported": "已导入",
        "processing": "处理中",
        "completed": "已完成",
        "failed": "处理失败",
        "pending": "等待处理",
        "running": "处理中",
        "succeeded": "已完成",
    }
    _CHECKPOINT_LABELS = {
        "imported": "已导入",
        "audio_extracted": "已抽取音频",
        "transcribed": "已生成原文字幕",
        "translated": "已生成译文字幕",
        "composed": "已完成合成",
        "exported": "已导出",
    }

    def __init__(self, task_service: TaskService) -> None:
        """创建任务列表和详情区，但不在构造阶段执行耗时工作。"""

        super().__init__()
        self.task_service = task_service

        # 左侧区域沿用桌面任务工具常见的操作方式：创建入口固定在顶部，
        # 历史视频按最近更新时间排列，选择一项后在右侧查看详细状态。
        self.create_task_button = QPushButton("创建视频任务")
        self.create_task_button.setObjectName("createVideoTaskButton")
        self.create_task_button.clicked.connect(
            lambda: self.create_requested.emit()
        )
        self.refresh_button = QPushButton("刷新")
        self.refresh_button.setObjectName("refreshVideoTasksButton")
        self.refresh_button.clicked.connect(lambda: self.refresh_history())
        task_actions = QHBoxLayout()
        task_actions.addWidget(self.create_task_button, 1)
        task_actions.addWidget(self.refresh_button)

        self.task_list = QListWidget()
        self.task_list.setObjectName("videoTaskList")
        self.task_list.setMinimumWidth(310)
        self.task_list.setSpacing(4)
        self.task_list.currentItemChanged.connect(self._show_history_item)

        history_group = QGroupBox("视频任务")
        history_layout = QVBoxLayout(history_group)
        history_layout.addLayout(task_actions)
        history_layout.addWidget(self.task_list, 1)

        # 右侧详情既显示持久化状态，也接收当前后台线程的进度事件。
        # 标签允许鼠标选择，便于用户复制任务编号、路径或错误信息进行排查。
        self.source_video_label = QLabel("-")
        self.project_id_label = QLabel("-")
        self.task_id_label = QLabel("-")
        self.task_type_label = QLabel("-")
        self.status_label = QLabel("空闲")
        self.step_label = QLabel("-")
        self.checkpoint_label = QLabel("-")
        self.retry_count_label = QLabel("0")
        self.message_label = QLabel("暂无任务")
        self.error_label = QLabel("无")
        self.workspace_label = QLabel("-")
        for label in (
            self.source_video_label,
            self.project_id_label,
            self.task_id_label,
            self.message_label,
            self.error_label,
            self.workspace_label,
        ):
            label.setWordWrap(True)
            label.setTextInteractionFlags(
                label.textInteractionFlags()
                | Qt.TextInteractionFlag.TextSelectableByMouse
            )

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("总进度 %p%")

        details_form = QFormLayout()
        details_form.addRow("源视频", self.source_video_label)
        details_form.addRow("项目编号", self.project_id_label)
        details_form.addRow("最近任务", self.task_id_label)
        details_form.addRow("当前阶段", self.task_type_label)
        details_form.addRow("状态", self.status_label)
        details_form.addRow("当前步骤", self.step_label)
        details_form.addRow("恢复检查点", self.checkpoint_label)
        details_form.addRow("重试次数", self.retry_count_label)
        details_form.addRow("任务消息", self.message_label)
        details_form.addRow("错误摘要", self.error_label)
        details_form.addRow("项目目录", self.workspace_label)

        self.translation_count_label = QLabel("尚未开始翻译")
        self.translation_preview = QPlainTextEdit()
        self.translation_preview.setObjectName("translationLivePreview")
        self.translation_preview.setReadOnly(True)
        self.translation_preview.setPlaceholderText(
            "逐句翻译开始后，原文和译文会实时追加到这里。"
        )
        self.translation_preview.document().setMaximumBlockCount(20_000)

        detail_group = QGroupBox("任务详情")
        detail_layout = QVBoxLayout(detail_group)
        detail_layout.addLayout(details_form)
        detail_layout.addWidget(self.progress_bar)

        translation_group = QGroupBox("逐句翻译实时结果")
        translation_layout = QVBoxLayout(translation_group)
        translation_layout.addWidget(self.translation_count_label)
        translation_layout.addWidget(self.translation_preview, 1)
        detail_layout.addWidget(translation_group, 1)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(history_group)
        splitter.addWidget(detail_group)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([340, 820])

        layout = QVBoxLayout(self)
        layout.addWidget(splitter, 1)

    def set_task_service(self, task_service: TaskService) -> None:
        """替换查询服务，并用新服务重新读取持久化任务历史。"""

        self.task_service = task_service
        self.refresh_history()

    def refresh_history(self, select_project_id: str | None = None) -> None:
        """从核心服务读取最近视频任务，并保持或恢复选中项目。

        这个方法只做短时间的 SQLite 查询。识别、翻译等长任务仍然通过
        后台线程执行，不会被放进 UI 线程。
        """

        if select_project_id is None:
            selected = self.task_list.currentItem()
            if selected is not None:
                selected_value = selected.data(Qt.ItemDataRole.UserRole)
                if isinstance(selected_value, VideoTaskHistoryDTO):
                    select_project_id = selected_value.project_id

        history = self.task_service.list_video_tasks()
        self.task_list.clear()
        selected_item: QListWidgetItem | None = None
        for item_value in history:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, item_value)
            self._update_history_item_text(item, item_value)
            self.task_list.addItem(item)
            if item_value.project_id == select_project_id:
                selected_item = item

        if self.task_list.count() == 0:
            placeholder = QListWidgetItem("暂无视频任务\n点击上方按钮创建第一个任务")
            placeholder.setFlags(
                placeholder.flags()
                & ~Qt.ItemFlag.ItemIsSelectable
                & ~Qt.ItemFlag.ItemIsEnabled
            )
            self.task_list.addItem(placeholder)
            return

        self.task_list.setCurrentItem(selected_item or self.task_list.item(0))

    def show_running(self) -> None:
        """在后台线程启动前把详情区切换为等待处理状态。"""

        self.status_label.setText("处理中")
        self.step_label.setText("等待创建项目")
        self.message_label.setText("任务已提交，等待后台处理")
        self.error_label.setText("无")
        self.progress_bar.setValue(0)
        self.translation_count_label.setText("等待字幕翻译")
        self.translation_preview.clear()

    def update_summary(self, summary: TaskSummaryDTO) -> None:
        """用最新任务摘要刷新详情，并更新对应视频的列表条目。"""

        self.project_id_label.setText(summary.project_id or "-")
        self.task_id_label.setText(summary.task_id)
        self.task_type_label.setText(self._task_type_text(summary.task_type))
        self.status_label.setText(self._status_text(summary.status))
        self.step_label.setText(summary.current_step or "-")
        self.message_label.setText(summary.message or "-")
        self.error_label.setText(
            summary.message if summary.status == "failed" else "无"
        )
        self.progress_bar.setValue(summary.progress)
        self._upsert_live_summary(summary)

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

    def _show_history_item(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        """把左侧选中的持久化记录展示到右侧详情。"""

        if current is None:
            return
        value = current.data(Qt.ItemDataRole.UserRole)
        if not isinstance(value, VideoTaskHistoryDTO):
            return

        self.source_video_label.setText(str(value.source_video))
        self.project_id_label.setText(value.project_id)
        self.task_id_label.setText(value.task_id or "-")
        self.task_type_label.setText(self._task_type_text(value.task_type))
        visible_status = self._visible_history_status(value)
        self.status_label.setText(self._status_text(visible_status))
        self.step_label.setText(value.current_step or "-")
        self.checkpoint_label.setText(
            self._CHECKPOINT_LABELS.get(value.checkpoint, value.checkpoint or "-")
        )
        self.retry_count_label.setText(str(value.retry_count))
        self.message_label.setText(value.message or "-")
        self.error_label.setText(value.error_message or "无")
        self.workspace_label.setText(str(value.workspace_dir))
        self.progress_bar.setValue(value.progress)

    def _upsert_live_summary(self, summary: TaskSummaryDTO) -> None:
        """把当前进度合并到对应视频条目，不为每个内部步骤新增一行。"""

        if not summary.project_id:
            return

        item = self._find_project_item(summary.project_id)
        if item is None:
            # 核心用例会先保存项目和任务再发布事件，所以新项目第一次出现时
            # 可以立即从仓储读取完整文件名和工作区信息。
            self.refresh_history(select_project_id=summary.project_id)
            item = self._find_project_item(summary.project_id)
            if item is None:
                return

        value = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(value, VideoTaskHistoryDTO):
            return

        if summary.status == "failed":
            project_status = "failed"
        elif summary.status == "running":
            project_status = "processing"
        else:
            project_status = value.project_status

        updated = replace(
            value,
            project_status=project_status,
            task_id=summary.task_id,
            task_type=summary.task_type,
            task_status=summary.status,
            progress=summary.progress,
            current_step=summary.current_step,
            message=summary.message,
            error_message=(
                summary.message if summary.status == "failed" else ""
            ),
        )
        item.setData(Qt.ItemDataRole.UserRole, updated)
        self._update_history_item_text(item, updated)
        self.task_list.setCurrentItem(item)

    def _find_project_item(self, project_id: str) -> QListWidgetItem | None:
        """按项目编号查找列表项，避免依赖会随排序变化的行号。"""

        for row in range(self.task_list.count()):
            item = self.task_list.item(row)
            value = item.data(Qt.ItemDataRole.UserRole)
            if (
                isinstance(value, VideoTaskHistoryDTO)
                and value.project_id == project_id
            ):
                return item
        return None

    def _update_history_item_text(
        self,
        item: QListWidgetItem,
        value: VideoTaskHistoryDTO,
    ) -> None:
        """用文件名、当前阶段和进度生成紧凑的任务列表摘要。"""

        status = self._visible_history_status(value)
        item.setText(
            "\n".join(
                [
                    value.source_video.name,
                    (
                        f"{self._task_type_text(value.task_type)} · "
                        f"{self._status_text(status)} · {value.progress}%"
                    ),
                    value.updated_at.astimezone().strftime("%Y-%m-%d %H:%M"),
                ]
            )
        )
        item.setToolTip(str(value.source_video))

    def _task_type_text(self, value: str) -> str:
        """把内部任务类型转换成面向用户的阶段名称。"""

        return self._TASK_TYPE_LABELS.get(value, value or "-")

    def _status_text(self, value: str) -> str:
        """把领域状态值转换成中文显示文字。"""

        return self._STATUS_LABELS.get(value, value or "-")

    def _visible_history_status(self, value: VideoTaskHistoryDTO) -> str:
        """选择最能解释当前阶段的状态，避免出现“处理中 100%”。

        项目完成或失败时，总状态最重要；其他情况下优先展示最近内部任务
        的状态。例如直接运行识别用例留下的旧项目可能仍是 processing，
        但最近识别任务已经 succeeded，此时显示“已完成”更符合事实。
        """

        if value.project_status in {"completed", "failed"}:
            return value.project_status
        return value.task_status or value.project_status
