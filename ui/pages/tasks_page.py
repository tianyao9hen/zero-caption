"""视频任务工作区页面。

页面属于 UI 层，负责展示持久化的视频任务列表、当前任务详情和逐句译文。
历史数据通过 `TaskService` 查询，页面不直接访问 SQLite，也不执行媒体处理。
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from core.domain.enums import ExportMode
from core.dto.subtitle_dto import (
    SubtitleTranslationItemDTO,
    TranslationProgressDTO,
)
from core.dto.task_dto import TaskSummaryDTO, VideoTaskHistoryDTO
from core.services.task_service import TaskService


class TasksPage(QWidget):
    """按视频组织任务历史，并展示当前处理阶段和实时译文。"""

    # 页面只发出“用户想创建任务”的意图，主窗口负责打开参数对话框并
    # 创建后台线程。这样页面不会承担主流程编排职责。
    create_requested = Signal()
    retry_requested = Signal(str, str)
    reexport_requested = Signal(str, str, str)
    save_translation_requested = Signal(str, str, str)
    retranslate_requested = Signal(str, str)

    _TASK_TYPE_LABELS = {
        "create_project": "导入视频",
        "transcribe_video": "生成字幕",
        "translate_subtitles": "逐句翻译",
        "edit_subtitle_translation": "编辑单句译文",
        "retranslate_subtitle": "重新翻译单句",
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
        self._subtitle_action_running = False
        self._active_project_operations = 0
        self._max_project_concurrency = 1
        self._active_project_ids: set[str] = set()
        self._selected_history_value: VideoTaskHistoryDTO | None = None
        self._has_complete_translation = False

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
        self.concurrency_label = QLabel("后台任务 0/1")
        self.concurrency_label.setObjectName("taskConcurrencyLabel")
        self.resource_policy_label = QLabel("识别与视频导出会自动排队串行执行")
        self.resource_policy_label.setObjectName("taskResourcePolicyLabel")
        self.resource_policy_label.setWordWrap(True)
        task_actions = QHBoxLayout()
        task_actions.addWidget(self.create_task_button, 1)
        task_actions.addWidget(self.concurrency_label)
        task_actions.addWidget(self.refresh_button)

        self.task_list = QListWidget()
        self.task_list.setObjectName("videoTaskList")
        self.task_list.setMinimumWidth(310)
        self.task_list.setSpacing(4)
        self.task_list.currentItemChanged.connect(self._show_history_item)

        history_group = QGroupBox("视频任务")
        history_layout = QVBoxLayout(history_group)
        history_layout.addLayout(task_actions)
        history_layout.addWidget(self.resource_policy_label)
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

        self.retry_button = QPushButton("从检查点继续")
        self.retry_button.setObjectName("retryVideoTaskButton")
        self.retry_button.setEnabled(False)
        self.retry_button.clicked.connect(self._request_retry)
        self.export_mode_combo = QComboBox()
        self.export_mode_combo.setObjectName("projectExportModeCombo")
        self.export_mode_combo.addItem(
            "外挂字幕",
            ExportMode.SOFT_SUBTITLE.value,
        )
        self.export_mode_combo.addItem("烧录字幕", ExportMode.BURN_IN.value)
        self.export_mode_combo.setEnabled(False)
        self.reexport_output_edit = QLineEdit()
        self.reexport_output_edit.setObjectName("reexportOutputPathField")
        self.reexport_output_edit.setPlaceholderText("选择重新导出的成品文件")
        self.reexport_output_edit.setEnabled(False)
        self.reexport_browse_button = QPushButton("浏览...")
        self.reexport_browse_button.setObjectName("browseReexportOutputButton")
        self.reexport_browse_button.setEnabled(False)
        self.reexport_browse_button.clicked.connect(
            self._browse_reexport_output
        )
        reexport_output_row = QHBoxLayout()
        reexport_output_row.addWidget(self.reexport_output_edit, 1)
        reexport_output_row.addWidget(self.reexport_browse_button)
        self.reexport_button = QPushButton("重新导出成品")
        self.reexport_button.setObjectName("reexportProjectButton")
        self.reexport_button.setEnabled(False)
        self.reexport_button.clicked.connect(self._request_reexport)
        project_actions = QHBoxLayout()
        project_actions.addWidget(self.retry_button)
        project_actions.addStretch(1)
        project_actions.addWidget(self.export_mode_combo)
        project_actions.addWidget(self.reexport_button)

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
        details_form.addRow("成品保存为", reexport_output_row)

        self.translation_count_label = QLabel("尚未加载字幕")
        self.subtitle_list = QListWidget()
        self.subtitle_list.setObjectName("subtitleTranslationList")
        self.subtitle_list.setSpacing(3)
        self.subtitle_list.currentItemChanged.connect(
            self._show_subtitle_item
        )

        self.selected_subtitle_label = QLabel("请选择一条已有译文的字幕")
        self.selected_subtitle_label.setWordWrap(True)
        self.subtitle_source_text = QPlainTextEdit()
        self.subtitle_source_text.setObjectName("selectedSubtitleSourceText")
        self.subtitle_source_text.setReadOnly(True)
        self.subtitle_source_text.setPlaceholderText("这里显示选中字幕的原文。")
        self.subtitle_source_text.setMaximumHeight(72)

        self.subtitle_translation_editor = QPlainTextEdit()
        self.subtitle_translation_editor.setObjectName(
            "selectedSubtitleTranslationEditor"
        )
        self.subtitle_translation_editor.setPlaceholderText(
            "选择已有译文后，可在这里修改翻译结果。"
        )
        self.subtitle_translation_editor.setMaximumHeight(88)

        self.save_translation_button = QPushButton("保存当前译文")
        self.save_translation_button.setObjectName("saveSubtitleTranslationButton")
        self.save_translation_button.setEnabled(False)
        self.save_translation_button.clicked.connect(
            self._request_save_translation
        )
        self.retranslate_button = QPushButton("重新翻译这一条")
        self.retranslate_button.setObjectName("retranslateSubtitleButton")
        self.retranslate_button.setEnabled(False)
        self.retranslate_button.clicked.connect(self._request_retranslation)
        translation_actions = QHBoxLayout()
        translation_actions.addWidget(self.save_translation_button)
        translation_actions.addWidget(self.retranslate_button)
        translation_actions.addStretch(1)

        self.subtitle_feedback_label = QLabel(
            "手工保存和重新翻译只更新字幕文件；已导出的视频不会自动改变。"
        )
        self.subtitle_feedback_label.setWordWrap(True)

        detail_group = QGroupBox("任务详情")
        detail_layout = QVBoxLayout(detail_group)
        detail_layout.addLayout(details_form)
        detail_layout.addWidget(self.progress_bar)
        detail_layout.addLayout(project_actions)

        translation_group = QGroupBox("字幕翻译结果与单句修订")
        translation_layout = QVBoxLayout(translation_group)
        translation_layout.addWidget(self.translation_count_label)
        translation_layout.addWidget(self.subtitle_list, 1)
        translation_layout.addWidget(self.selected_subtitle_label)
        translation_layout.addWidget(QLabel("原文"))
        translation_layout.addWidget(self.subtitle_source_text)
        translation_layout.addWidget(QLabel("译文"))
        translation_layout.addWidget(self.subtitle_translation_editor)
        translation_layout.addLayout(translation_actions)
        translation_layout.addWidget(self.subtitle_feedback_label)

        detail_splitter = QSplitter(Qt.Orientation.Vertical)
        detail_splitter.addWidget(detail_group)
        detail_splitter.addWidget(translation_group)
        detail_splitter.setStretchFactor(0, 0)
        detail_splitter.setStretchFactor(1, 1)
        detail_splitter.setSizes([300, 470])

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(history_group)
        splitter.addWidget(detail_splitter)
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
            self._selected_history_value = None
            self._has_complete_translation = False
            self._sync_project_actions()
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
        self.subtitle_list.clear()
        self._clear_subtitle_editor()

    def set_project_operation_capacity(
        self,
        active_count: int,
        max_concurrency: int,
        message: str = "",
        active_project_ids: set[str] | None = None,
    ) -> None:
        """显示后台视频流程用量，并在达到上限时暂停继续提交。

        参数：
            active_count：当前仍在运行的视频级后台线程数量。
            max_concurrency：配置允许同时运行的最大视频流程数量。
            message：可选的当前操作提示。
            active_project_ids：正在恢复或重新导出的已有项目编号。

        这个方法只更新界面可用状态。真正的高资源串行约束由核心服务和
        基础设施调度器保证，不能依赖按钮是否启用来维护并发安全。
        """

        self._active_project_operations = max(0, active_count)
        self._max_project_concurrency = max(1, max_concurrency)
        self._active_project_ids = set(active_project_ids or ())
        has_capacity = self._active_project_operations < self._max_project_concurrency
        self.create_task_button.setEnabled(has_capacity)
        self.concurrency_label.setText(
            f"后台任务 {self._active_project_operations}/"
            f"{self._max_project_concurrency}"
        )
        if message:
            self.message_label.setText(message)
        self._sync_project_actions()

    def set_project_action_running(self, running: bool, message: str = "") -> None:
        """兼容旧调用方，把单任务忙碌状态映射到容量显示。"""

        self.set_project_operation_capacity(
            active_count=1 if running else 0,
            max_concurrency=1,
            message=message,
        )

    def update_summary(self, summary: TaskSummaryDTO) -> None:
        """更新对应视频条目，仅在它被选中时刷新右侧详情。

        多个任务会交错发布进度事件。未选中任务的事件只更新左侧摘要，
        不会抢走用户正在查看或编辑的另一个视频。
        """

        item = self._upsert_live_summary(summary)
        if item is None or self.task_list.currentItem() is not item:
            return

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

    def update_translation_progress(self, progress: TranslationProgressDTO) -> None:
        """把后台刚完成的一条译文实时更新到可选择的字幕列表。"""

        selected_project_id = self.project_id_label.text()
        if (
            progress.project_id
            and selected_project_id not in {"-", progress.project_id}
        ):
            return

        self.translation_count_label.setText(
            f"已完成 {progress.current_index}/{progress.total_segments} 条"
        )
        self._upsert_subtitle_item(
            SubtitleTranslationItemDTO(
                project_id=progress.project_id or selected_project_id,
                segment_id=progress.segment_id or f"live-{progress.current_index}",
                current_index=progress.current_index,
                total_segments=progress.total_segments,
                start_ms=progress.start_ms,
                end_ms=progress.end_ms,
                source_text=progress.source_text,
                translated_text=progress.translated_text,
            )
        )

    def set_subtitle_action_running(self, running: bool, message: str) -> None:
        """切换单句修订的忙碌状态，避免用户重复提交同一操作。"""

        self._subtitle_action_running = running
        current = self._selected_subtitle()
        has_translation = bool(current and current.translated_text.strip())
        self.save_translation_button.setEnabled(not running and has_translation)
        self.retranslate_button.setEnabled(not running and has_translation)
        self.subtitle_translation_editor.setReadOnly(running)
        self.subtitle_feedback_label.setText(message)

    def show_subtitle_update_result(
        self,
        item: SubtitleTranslationItemDTO,
        message: str,
    ) -> None:
        """展示核心服务返回的新译文，并恢复编辑按钮。"""

        self._upsert_subtitle_item(item, select=True)
        self.set_subtitle_action_running(False, message)

    def show_subtitle_update_error(self, message: str) -> None:
        """在页面内展示修订错误，同时保留用户编辑中的文本。"""

        self.set_subtitle_action_running(False, message)

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

        self._selected_history_value = value
        self._has_complete_translation = False
        self._select_export_mode(value.export_mode)
        self.reexport_output_edit.setText(
            str(value.output_path or self._default_reexport_path(value))
        )

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
        self._load_subtitle_translations(value.project_id)
        self._sync_project_actions()

    def _load_subtitle_translations(
        self,
        project_id: str,
        select_segment_id: str | None = None,
    ) -> None:
        """通过核心服务加载项目字幕，不让页面直接访问仓储。"""

        try:
            items = self.task_service.list_subtitle_translations(project_id)
        except (RuntimeError, ValueError) as exc:
            self._has_complete_translation = False
            self.subtitle_list.clear()
            self.translation_count_label.setText(f"字幕暂不可用：{exc}")
            self._clear_subtitle_editor()
            return

        self.subtitle_list.clear()
        selected_item: QListWidgetItem | None = None
        translated_count = 0
        for item_value in items:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, item_value)
            self._update_subtitle_item_text(item, item_value)
            self.subtitle_list.addItem(item)
            if item_value.translated_text.strip():
                translated_count += 1
            if item_value.segment_id == select_segment_id:
                selected_item = item

        if not items:
            self._has_complete_translation = False
            self.translation_count_label.setText("这个项目尚未生成原文字幕")
            self._clear_subtitle_editor()
            return
        self.translation_count_label.setText(
            f"已有译文 {translated_count}/{len(items)} 条"
        )
        self._has_complete_translation = translated_count == len(items)
        self.subtitle_list.setCurrentItem(selected_item or self.subtitle_list.item(0))
        self._sync_project_actions()

    def _request_retry(self) -> None:
        """把当前失败项目的继续处理意图发给主窗口。"""

        value = self._selected_history_value
        if value is None:
            return
        self.retry_requested.emit(value.project_id, value.processing_mode)

    def _request_reexport(self) -> None:
        """把当前项目、导出模式和用户选择的成品路径发给主窗口。"""

        value = self._selected_history_value
        mode_value = self.export_mode_combo.currentData()
        if value is None or not isinstance(mode_value, str):
            return
        output_text = self.reexport_output_edit.text().strip()
        if not output_text:
            QMessageBox.warning(self, "无法重新导出", "请选择成品保存位置。")
            return

        # 后台任务可能在应用重启后运行，持久化前先消除相对路径歧义。
        output_path = Path(output_text).resolve()
        if not output_path.suffix:
            output_path = output_path.with_suffix(
                value.source_video.suffix or ".mp4"
            )
            self.reexport_output_edit.setText(str(output_path))
        if output_path.exists() and output_path.is_dir():
            QMessageBox.warning(
                self,
                "无法重新导出",
                "成品保存位置必须是文件路径，不能是目录。",
            )
            return
        if output_path.resolve() == value.source_video.resolve():
            QMessageBox.warning(
                self,
                "无法重新导出",
                "成品保存路径不能覆盖源视频，请使用其他文件名。",
            )
            return
        if output_path.exists():
            overwrite = QMessageBox.question(
                self,
                "确认覆盖",
                f"目标文件已经存在，是否覆盖？\n{output_path}",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if overwrite != QMessageBox.StandardButton.Yes:
                return
        self.reexport_requested.emit(
            value.project_id,
            mode_value,
            str(output_path),
        )

    def _browse_reexport_output(self) -> None:
        """打开文件保存对话框，为重新导出的成品选择完整路径。"""

        value = self._selected_history_value
        if value is None:
            return
        initial_path = self.reexport_output_edit.text().strip()
        if not initial_path:
            initial_path = str(self._default_reexport_path(value))
        suffix = value.source_video.suffix or ".mp4"
        selected_path, _ = QFileDialog.getSaveFileName(
            self,
            "选择重新导出文件",
            initial_path,
            f"视频文件 (*{suffix});;所有文件 (*.*)",
        )
        if selected_path:
            self.reexport_output_edit.setText(selected_path)

    @staticmethod
    def _default_reexport_path(value: VideoTaskHistoryDTO) -> Path:
        """为从未导出的旧项目生成不会覆盖源视频的建议路径。"""

        suffix = value.source_video.suffix or ".mp4"
        return (
            value.workspace_dir
            / "exports"
            / f"{value.source_video.stem}-字幕{suffix}"
        )

    def _select_export_mode(self, mode_value: str) -> None:
        """让导出模式控件显示项目上次保存的选择。"""

        for index in range(self.export_mode_combo.count()):
            if self.export_mode_combo.itemData(index) == mode_value:
                self.export_mode_combo.setCurrentIndex(index)
                return

    def _sync_project_actions(self) -> None:
        """根据当前项目状态启用恢复与重新导出操作。"""

        value = self._selected_history_value
        available = (
            value is not None
            and self._active_project_operations < self._max_project_concurrency
            and value.project_id not in self._active_project_ids
        )
        retryable = available and (
            value.project_status == "failed" or value.task_status == "pending"
        )
        exportable = (
            available
            and value.processing_mode == "full_pipeline"
            and self._has_complete_translation
        )
        self.retry_button.setEnabled(bool(retryable))
        self.export_mode_combo.setEnabled(bool(exportable))
        self.reexport_output_edit.setEnabled(bool(exportable))
        self.reexport_browse_button.setEnabled(bool(exportable))
        self.reexport_button.setEnabled(bool(exportable))

    def _show_subtitle_item(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        """把选中字幕的原文和译文填入编辑区域。"""

        if current is None:
            self._clear_subtitle_editor()
            return
        value = current.data(Qt.ItemDataRole.UserRole)
        if not isinstance(value, SubtitleTranslationItemDTO):
            self._clear_subtitle_editor()
            return

        self.selected_subtitle_label.setText(
            f"第 {value.current_index}/{value.total_segments} 条 · "
            f"{self._format_timestamp(value.start_ms)} → "
            f"{self._format_timestamp(value.end_ms)}"
        )
        self.subtitle_source_text.setPlainText(value.source_text)
        self.subtitle_translation_editor.setPlainText(value.translated_text)
        has_translation = bool(value.translated_text.strip())
        enabled = has_translation and not self._subtitle_action_running
        self.save_translation_button.setEnabled(enabled)
        self.retranslate_button.setEnabled(enabled)

    def _request_save_translation(self) -> None:
        """校验当前选择，并把手工译文保存意图发给主窗口。"""

        value = self._selected_subtitle()
        translated_text = self.subtitle_translation_editor.toPlainText().strip()
        if value is None:
            self.subtitle_feedback_label.setText("请先选择一条字幕。")
            return
        if not translated_text:
            self.subtitle_feedback_label.setText("字幕译文不能为空。")
            return
        self.save_translation_requested.emit(
            value.project_id,
            value.segment_id,
            translated_text,
        )

    def _request_retranslation(self) -> None:
        """把当前选中字幕的单句重译意图发给主窗口。"""

        value = self._selected_subtitle()
        if value is None or not value.translated_text.strip():
            self.subtitle_feedback_label.setText("请先选择一条已有译文的字幕。")
            return
        self.retranslate_requested.emit(value.project_id, value.segment_id)

    def _selected_subtitle(self) -> SubtitleTranslationItemDTO | None:
        """返回当前选中的字幕 DTO，不把列表行号当成业务编号。"""

        current = self.subtitle_list.currentItem()
        if current is None:
            return None
        value = current.data(Qt.ItemDataRole.UserRole)
        return value if isinstance(value, SubtitleTranslationItemDTO) else None

    def _upsert_subtitle_item(
        self,
        value: SubtitleTranslationItemDTO,
        select: bool = False,
    ) -> None:
        """按字幕编号更新实时结果；不存在时按原文序号插入。"""

        target_item: QListWidgetItem | None = None
        for row in range(self.subtitle_list.count()):
            item = self.subtitle_list.item(row)
            existing = item.data(Qt.ItemDataRole.UserRole)
            if (
                isinstance(existing, SubtitleTranslationItemDTO)
                and existing.segment_id == value.segment_id
            ):
                target_item = item
                break

        if target_item is None:
            target_item = QListWidgetItem()
            insert_row = max(0, min(value.current_index - 1, self.subtitle_list.count()))
            self.subtitle_list.insertItem(insert_row, target_item)
        target_item.setData(Qt.ItemDataRole.UserRole, value)
        self._update_subtitle_item_text(target_item, value)
        if select or self.subtitle_list.currentItem() is target_item:
            self.subtitle_list.setCurrentItem(target_item)
            self._show_subtitle_item(target_item, None)

    def _update_subtitle_item_text(
        self,
        item: QListWidgetItem,
        value: SubtitleTranslationItemDTO,
    ) -> None:
        """生成包含序号、时间、原文和译文的两行列表摘要。"""

        translated_text = value.translated_text or "（尚无译文）"
        item.setText(
            "\n".join(
                [
                    (
                        f"{value.current_index}. "
                        f"{self._format_timestamp(value.start_ms)}  "
                        f"原文：{value.source_text}"
                    ),
                    f"译文：{translated_text}",
                ]
            )
        )
        item.setToolTip(f"字幕编号：{value.segment_id}")

    def _clear_subtitle_editor(self) -> None:
        """清空选择区并禁用需要已有译文的操作。"""

        self.selected_subtitle_label.setText("请选择一条已有译文的字幕")
        self.subtitle_source_text.clear()
        self.subtitle_translation_editor.clear()
        self.save_translation_button.setEnabled(False)
        self.retranslate_button.setEnabled(False)

    @staticmethod
    def _format_timestamp(milliseconds: int) -> str:
        """把毫秒转换为紧凑的界面时间，便于定位视频位置。"""

        safe_value = max(0, milliseconds)
        minutes, remainder = divmod(safe_value, 60_000)
        seconds, millis = divmod(remainder, 1_000)
        return f"{minutes:02}:{seconds:02}.{millis:03}"

    def _upsert_live_summary(
        self,
        summary: TaskSummaryDTO,
    ) -> QListWidgetItem | None:
        """把当前进度合并到对应视频条目，不为每个内部步骤新增一行。"""

        if not summary.project_id:
            return None

        item = self._find_project_item(summary.project_id)
        if item is None:
            # 核心用例会先保存项目和任务再发布事件，所以新项目第一次出现时
            # 可以立即从仓储读取完整文件名和工作区信息。
            self.refresh_history(select_project_id=summary.project_id)
            item = self._find_project_item(summary.project_id)
            if item is None:
                return None

        value = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(value, VideoTaskHistoryDTO):
            return None

        revision_task_types = {
            "edit_subtitle_translation",
            "retranslate_subtitle",
        }
        if summary.task_type in revision_task_types:
            # 单句修订是项目完成后的附加动作。它的失败只属于本次操作，
            # 不能把整个视频项目的持久化状态伪装成失败或处理中。
            project_status = value.project_status
        elif summary.status == "failed":
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
        if self.task_list.currentItem() is item:
            self._selected_history_value = updated
            self._sync_project_actions()
        return item

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

        if value.task_type in {
            "edit_subtitle_translation",
            "retranslate_subtitle",
        }:
            return value.task_status or value.project_status
        if value.project_status in {"completed", "failed"}:
            return value.project_status
        return value.task_status or value.project_status
