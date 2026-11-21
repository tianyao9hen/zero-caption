"""视频任务工作区页面。

页面属于 UI 层，负责展示持久化的视频任务列表、当前任务详情和逐句译文。
历史数据通过 `TaskService` 查询，页面不直接访问 SQLite，也不执行媒体处理。
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
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
    # 批量删除时携带一组 `(项目编号, 项目目录)`，页面只收集用户选择，
    # 真正的项目级清理仍由核心服务执行。
    delete_requested = Signal(list)
    retry_requested = Signal(str, str)
    download_requested = Signal(str, str, str)
    save_translation_requested = Signal(str, str, str)
    retranslate_requested = Signal(str, str)

    _TASK_TYPE_LABELS = {
        "create_project": "导入视频",
        "transcribe_video": "生成字幕",
        "translate_subtitles": "逐句翻译",
        "edit_subtitle_translation": "编辑单句译文",
        "retranslate_subtitle": "重新翻译单句",
        "export_video": "下载成品",
        # 烧录任务在创建时就先在工作区烧录成品，这一步对用户来说是“生成成品”，
        # 和用户稍后点击“下载成品”复制文件区分开。
        "prepare_product": "生成成品",
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
        "exported": "已生成下载成品",
    }

    def __init__(self, task_service: TaskService) -> None:
        """创建任务列表和详情区，但不在构造阶段执行耗时工作。"""

        super().__init__()
        self.task_service = task_service
        self._subtitle_action_running = False
        self._active_project_operations = 0
        self._max_project_concurrency = 1
        self._active_project_ids: set[str] = set()
        # 正在生成下载成品的项目单独记录。识别任务与成品导出是两类不同的
        # 后台操作，只有同一个项目正在导出时才需要临时禁用它的下载按钮。
        self._exporting_project_ids: set[str] = set()
        self._selected_history_value: VideoTaskHistoryDTO | None = None
        self._has_complete_translation = False
        # 识别并发上限由设置页配置后传进来，用于在界面上解释排队原因。
        self._recognition_parallelism = 1

        # 左侧区域沿用桌面任务工具常见的操作方式：创建入口固定在顶部，
        # 历史视频按最近更新时间排列，选择一项后在右侧查看详细状态。
        self.create_task_button = QPushButton("新建任务")
        self.create_task_button.setObjectName("createVideoTaskButton")
        self.create_task_button.clicked.connect(
            lambda: self.create_requested.emit()
        )
        self.refresh_button = QPushButton("刷新")
        self.refresh_button.setObjectName("refreshVideoTasksButton")
        self.refresh_button.clicked.connect(lambda: self.refresh_history())
        self.delete_button = QPushButton("删除任务")
        self.delete_button.setObjectName("deleteVideoTaskButton")
        self.delete_button.setEnabled(False)
        self.delete_button.setToolTip(
            "支持按住 Ctrl 或 Shift 多选，一次删除多个任务。"
        )
        self.delete_button.clicked.connect(self._request_delete)
        self.concurrency_label = QLabel("后台 0（创建不限量）")
        self.concurrency_label.setObjectName("taskConcurrencyLabel")
        self.resource_policy_label = QLabel("识别与视频下载生成会自动排队串行执行")
        self.resource_policy_label.setObjectName("taskResourcePolicyLabel")
        self.resource_policy_label.setToolTip(
            "识别和视频下载生成按创建顺序排队执行，可在设置页调整并发数"
        )
        task_actions = QHBoxLayout()
        task_actions.setSpacing(6)
        task_actions.addWidget(self.create_task_button, 1)
        task_actions.addWidget(self.concurrency_label)
        task_actions.addWidget(self.delete_button)
        task_actions.addWidget(self.refresh_button)

        self.task_list = QListWidget()
        self.task_list.setObjectName("videoTaskList")
        self.task_list.setMinimumWidth(280)
        self.task_list.setSpacing(2)
        # 允许 Ctrl 多选和 Shift 连选，删除按钮据此批量清理任务。
        self.task_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.task_list.currentItemChanged.connect(self._show_history_item)

        history_group = QGroupBox("视频任务")
        history_layout = QVBoxLayout(history_group)
        history_layout.setContentsMargins(8, 6, 8, 8)
        history_layout.setSpacing(6)
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
        # 外部工具失败信息可能包含数千行日志。任务详情只承担摘要展示，
        # 因此限制高度，避免长日志把下方的字幕翻译主视图挤出首屏。
        # 完整文本仍通过鼠标悬停提示和可选择文本保留给诊断使用。
        self.message_label.setMaximumHeight(42)
        self.error_label.setMaximumHeight(42)
        for label in (
            self.source_video_label,
            self.project_id_label,
            self.task_id_label,
            self.message_label,
            self.error_label,
            self.workspace_label,
        ):
            # 编号和路径通常没有天然换行点；忽略它们的横向尺寸提示，
            # 才能让窗口在窄屏上按网格列宽换行，而不是被长文本强制撑宽。
            label.setSizePolicy(
                QSizePolicy.Policy.Ignored,
                QSizePolicy.Policy.Preferred,
            )
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
        self.download_button = QPushButton("下载成品...")
        self.download_button.setObjectName("downloadProjectButton")
        self.download_button.setEnabled(False)
        self.download_button.clicked.connect(self._request_download)
        project_actions = QHBoxLayout()
        project_actions.setSpacing(6)
        project_actions.addWidget(self.retry_button)
        project_actions.addStretch(1)
        project_actions.addWidget(self.export_mode_combo)
        project_actions.addWidget(self.download_button)

        # 详情值本身没有业务层级差异，因此用多列网格并排展示关联信息。
        # 这样保持全部诊断字段可见，同时把十一行压缩为六行。
        details_grid = QGridLayout()
        details_grid.setObjectName("taskDetailsGrid")
        details_grid.setContentsMargins(0, 0, 0, 0)
        details_grid.setHorizontalSpacing(8)
        details_grid.setVerticalSpacing(3)
        details_grid.addWidget(QLabel("源视频"), 0, 0)
        details_grid.addWidget(self.source_video_label, 0, 1, 1, 5)
        details_grid.addWidget(QLabel("项目编号"), 1, 0)
        details_grid.addWidget(self.project_id_label, 1, 1)
        details_grid.addWidget(QLabel("最近任务"), 1, 2)
        details_grid.addWidget(self.task_id_label, 1, 3, 1, 3)
        details_grid.addWidget(QLabel("当前阶段"), 2, 0)
        details_grid.addWidget(self.task_type_label, 2, 1)
        details_grid.addWidget(QLabel("状态"), 2, 2)
        details_grid.addWidget(self.status_label, 2, 3)
        details_grid.addWidget(QLabel("恢复检查点"), 2, 4)
        details_grid.addWidget(self.checkpoint_label, 2, 5)
        details_grid.addWidget(QLabel("当前步骤"), 3, 0)
        details_grid.addWidget(self.step_label, 3, 1, 1, 3)
        details_grid.addWidget(QLabel("重试次数"), 3, 4)
        details_grid.addWidget(self.retry_count_label, 3, 5)
        details_grid.addWidget(QLabel("任务消息"), 4, 0)
        details_grid.addWidget(self.message_label, 4, 1)
        details_grid.addWidget(QLabel("错误摘要"), 4, 2)
        details_grid.addWidget(self.error_label, 4, 3, 1, 3)
        details_grid.addWidget(QLabel("项目目录"), 5, 0)
        details_grid.addWidget(self.workspace_label, 5, 1, 1, 5)
        details_grid.setColumnStretch(1, 2)
        details_grid.setColumnStretch(3, 2)
        details_grid.setColumnStretch(5, 1)

        self.translation_count_label = QLabel("尚未加载字幕")
        self.subtitle_list = QListWidget()
        self.subtitle_list.setObjectName("subtitleTranslationList")
        self.subtitle_list.setSpacing(2)
        self.subtitle_list.setMinimumHeight(210)
        self.subtitle_list.currentItemChanged.connect(
            self._show_subtitle_item
        )

        self.selected_subtitle_label = QLabel("请选择一条已有译文的字幕")
        self.selected_subtitle_label.setWordWrap(True)
        self.subtitle_source_text = QPlainTextEdit()
        self.subtitle_source_text.setObjectName("selectedSubtitleSourceText")
        self.subtitle_source_text.setReadOnly(True)
        self.subtitle_source_text.setPlaceholderText("这里显示选中字幕的原文。")
        self.subtitle_source_text.setMinimumHeight(64)

        self.subtitle_translation_editor = QPlainTextEdit()
        self.subtitle_translation_editor.setObjectName(
            "selectedSubtitleTranslationEditor"
        )
        self.subtitle_translation_editor.setPlaceholderText(
            "选择已有译文后，可在这里修改翻译结果。"
        )
        self.subtitle_translation_editor.setMinimumHeight(96)

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
        translation_actions.setSpacing(6)
        translation_actions.addWidget(self.save_translation_button)
        translation_actions.addWidget(self.retranslate_button)
        translation_actions.addStretch(1)

        self.subtitle_feedback_label = QLabel(
            "保存或重译只更新字幕；烧录成品会在下一次下载时按最新译文刷新。"
        )
        self.subtitle_feedback_label.setWordWrap(True)

        detail_group = QGroupBox("任务详情")
        detail_layout = QVBoxLayout(detail_group)
        detail_layout.setContentsMargins(8, 6, 8, 8)
        detail_layout.setSpacing(6)
        detail_layout.addLayout(details_grid)
        detail_layout.addWidget(self.progress_bar)
        detail_layout.addLayout(project_actions)

        translation_group = QGroupBox("字幕翻译结果与单句修订")
        translation_layout = QVBoxLayout(translation_group)
        translation_layout.setContentsMargins(8, 6, 8, 8)
        translation_layout.setSpacing(6)

        # 左侧把全部字幕结果作为主视图，翻译事件到达时会实时追加。
        # 单句修订移到右侧后不再挤占主视图高度，用户可以连续查看更长的
        # 翻译过程，同时仍能选择任意一条进行校对。
        translation_result_panel = QWidget()
        translation_result_layout = QVBoxLayout(translation_result_panel)
        translation_result_layout.setContentsMargins(0, 0, 0, 0)
        translation_result_layout.setSpacing(4)
        translation_result_header = QHBoxLayout()
        translation_result_header.addWidget(QLabel("全部字幕翻译过程"))
        translation_result_header.addStretch(1)
        translation_result_header.addWidget(self.translation_count_label)
        translation_result_layout.addLayout(translation_result_header)
        translation_result_layout.addWidget(self.subtitle_list, 1)

        revision_group = QGroupBox("单句修订")
        revision_layout = QVBoxLayout(revision_group)
        revision_layout.setContentsMargins(8, 6, 8, 8)
        revision_layout.setSpacing(4)
        revision_layout.addWidget(self.selected_subtitle_label)
        revision_layout.addWidget(QLabel("原文"))
        revision_layout.addWidget(self.subtitle_source_text, 1)
        revision_layout.addWidget(QLabel("已有译文 / 修订译文"))
        revision_layout.addWidget(self.subtitle_translation_editor, 2)
        revision_layout.addLayout(translation_actions)
        revision_layout.addWidget(self.subtitle_feedback_label)

        translation_splitter = QSplitter(Qt.Orientation.Horizontal)
        translation_splitter.setObjectName("subtitleTranslationSplitter")
        translation_splitter.addWidget(translation_result_panel)
        translation_splitter.addWidget(revision_group)
        translation_splitter.setStretchFactor(0, 2)
        translation_splitter.setStretchFactor(1, 1)
        translation_splitter.setSizes([560, 320])
        translation_layout.addWidget(translation_splitter, 1)

        # 翻译失败清单独立于主字幕列表。逐条列出失败原因，点击即可跳到
        # 上方主列表中的同一条字幕，直接进入人工修订流程。
        failure_group = QGroupBox("翻译失败清单")
        failure_group.setObjectName("translationFailureGroup")
        failure_layout = QVBoxLayout(failure_group)
        failure_layout.setContentsMargins(8, 6, 8, 8)
        failure_layout.setSpacing(4)
        self.failure_count_label = QLabel("当前项目没有翻译失败的字幕。")
        self.failure_count_label.setObjectName("translationFailureCountLabel")
        self.failure_count_label.setWordWrap(True)
        self.failed_subtitle_list = QListWidget()
        self.failed_subtitle_list.setObjectName("failedSubtitleList")
        self.failed_subtitle_list.setSpacing(2)
        self.failed_subtitle_list.setMaximumHeight(120)
        self.failed_subtitle_list.setToolTip("点击失败条目可跳转到对应字幕进行人工处理。")
        self.failed_subtitle_list.itemClicked.connect(self._jump_to_failed_subtitle)
        failure_layout.addWidget(self.failure_count_label)
        failure_layout.addWidget(self.failed_subtitle_list)
        self.failure_group = failure_group
        # 没有失败条目时整组隐藏，不占用主视图高度。
        failure_group.setVisible(False)
        translation_layout.addWidget(failure_group)

        detail_splitter = QSplitter(Qt.Orientation.Vertical)
        detail_splitter.addWidget(detail_group)
        detail_splitter.addWidget(translation_group)
        detail_splitter.setStretchFactor(0, 0)
        detail_splitter.setStretchFactor(1, 1)
        detail_splitter.setSizes([190, 490])

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(history_group)
        splitter.addWidget(detail_splitter)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([310, 790])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter, 1)

        # `currentItemChanged` 只在“当前项”变化时触发，按住 Ctrl 追加或取消
        # 选择其他条目并不会改变当前项，删除按钮就会停在旧状态。
        # 因此再订阅一次选择集合变化，并且放在构造函数最后连接，
        # 确保首次触发时所有按钮控件都已经创建完成。
        self.task_list.itemSelectionChanged.connect(self._sync_project_actions)

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
        self._sync_failure_list([])
        self._clear_subtitle_editor()

    def set_project_operation_capacity(
        self,
        active_count: int,
        max_concurrency: int,
        message: str = "",
        active_project_ids: set[str] | None = None,
        exporting_project_ids: set[str] | None = None,
        recognition_parallelism: int | None = None,
    ) -> None:
        """显示后台视频流程用量，但不限制用户继续创建视频任务。

        参数：
            active_count：当前仍在运行的视频级后台线程数量。
            max_concurrency：保留用于兼容旧调用方的配置值；它不再是创建门槛。
            message：可选的当前操作提示。
            active_project_ids：正在识别或翻译的已有项目编号。
            exporting_project_ids：正在生成下载成品的项目编号。
            recognition_parallelism：识别并发上限，用于在界面上说明排队方式。

        这个方法只更新界面可用状态。真正的高资源串行约束由核心服务和
        基础设施调度器保证，不能依赖按钮是否启用来维护并发安全。
        """

        self._active_project_operations = max(0, active_count)
        self._max_project_concurrency = max(1, max_concurrency)
        self._active_project_ids = set(active_project_ids or ())
        self._exporting_project_ids = set(exporting_project_ids or ())
        if recognition_parallelism is not None:
            self._recognition_parallelism = max(1, recognition_parallelism)
        # 视频任务可以无限创建。高资源步骤是否串行由核心层的资源调度器
        # 决定，不能用“禁用创建按钮”的方式把待处理任务挡在 UI 外面。
        self.create_task_button.setEnabled(True)
        self.concurrency_label.setText(
            f"后台 {self._active_project_operations}（创建不限量）"
        )
        self.resource_policy_label.setText(
            "识别按创建顺序排队执行"
            f"（同时 {self._recognition_parallelism} 个），下载成品独立排队"
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
        self.message_label.setToolTip(summary.message or "")
        self.error_label.setToolTip(
            summary.message if summary.status == "failed" else ""
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
            (
                f"已跳过失败 {progress.current_index}/{progress.total_segments} 条"
                if progress.translation_error
                else f"已完成 {progress.current_index}/{progress.total_segments} 条"
            )
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
                translation_error=progress.translation_error,
            )
        )

    def set_subtitle_action_running(self, running: bool, message: str) -> None:
        """切换单句修订的忙碌状态，避免用户重复提交同一操作。"""

        self._subtitle_action_running = running
        current = self._selected_subtitle()
        has_selection = current is not None
        self.save_translation_button.setEnabled(not running and has_selection)
        self.retranslate_button.setEnabled(not running and has_selection)
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
            # 刷新列表清空选择、或用户主动取消选中时会走到这里。
            # 必须把缓存的项目状态一起清空，否则重试、下载等按钮会残留
            # 上一个项目的能力，出现“没有选中任务却能点下载”的错觉。
            self._selected_history_value = None
            self._has_complete_translation = False
            self._sync_project_actions()
            return
        value = current.data(Qt.ItemDataRole.UserRole)
        if not isinstance(value, VideoTaskHistoryDTO):
            return

        self._selected_history_value = value
        self._has_complete_translation = False
        self._select_export_mode(value.export_mode)

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
        self.message_label.setToolTip(value.message or "")
        self.error_label.setToolTip(value.error_message or "")
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
            self._sync_failure_list([])
            return

        self.subtitle_list.clear()
        selected_item: QListWidgetItem | None = None
        translated_count = 0
        failed_items: list[SubtitleTranslationItemDTO] = []
        for item_value in items:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, item_value)
            self._update_subtitle_item_text(item, item_value)
            self.subtitle_list.addItem(item)
            if item_value.translated_text.strip():
                translated_count += 1
            elif item_value.translation_error:
                # 只有既没有译文又记录了失败原因，才算需要人工处理的条目。
                failed_items.append(item_value)
            if item_value.segment_id == select_segment_id:
                selected_item = item

        self._sync_failure_list(failed_items)
        if not items:
            self._has_complete_translation = False
            self.translation_count_label.setText("这个项目尚未生成原文字幕")
            self._clear_subtitle_editor()
            return
        self.translation_count_label.setText(
            f"已有译文 {translated_count}/{len(items)} 条"
        )
        self._has_complete_translation = (
            translated_count == len(items) and not failed_items
        )
        self.subtitle_list.setCurrentItem(selected_item or self.subtitle_list.item(0))
        self._sync_project_actions()

    def _sync_failure_list(
        self,
        failed_items: list[SubtitleTranslationItemDTO],
    ) -> None:
        """重建翻译失败清单，让用户能直接定位到需要人工处理的字幕。"""

        self.failed_subtitle_list.clear()
        if not failed_items:
            self.failure_group.setVisible(False)
            self.failure_count_label.setText("当前项目没有翻译失败的字幕。")
            return

        self.failure_group.setVisible(True)
        self.failure_count_label.setText(
            f"共 {len(failed_items)} 条字幕翻译失败，点击可跳转到对应字幕人工处理。"
        )
        for item_value in failed_items:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, item_value)
            item.setText(
                f"{item_value.current_index}. "
                f"{self._format_timestamp(item_value.start_ms)}  "
                f"{item_value.source_text}\n"
                f"失败原因：{item_value.translation_error}"
            )
            item.setToolTip(f"字幕编号：{item_value.segment_id}")
            self.failed_subtitle_list.addItem(item)

    def _jump_to_failed_subtitle(self, item: QListWidgetItem) -> None:
        """把失败清单中的条目定位到主字幕列表，并载入单句修订区。"""

        value = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(value, SubtitleTranslationItemDTO):
            return
        for row in range(self.subtitle_list.count()):
            target = self.subtitle_list.item(row)
            existing = target.data(Qt.ItemDataRole.UserRole)
            if (
                isinstance(existing, SubtitleTranslationItemDTO)
                and existing.segment_id == value.segment_id
            ):
                self.subtitle_list.setCurrentItem(target)
                self.subtitle_list.scrollToItem(target)
                self.subtitle_feedback_label.setText(
                    f"已定位到第 {value.current_index} 条失败字幕，"
                    "可手工填写译文后保存，或点击“重新翻译这一条”。"
                )
                return
        self.subtitle_feedback_label.setText(
            "该失败字幕已不在当前字幕列表中，请刷新项目后再试。"
        )

    def _request_retry(self) -> None:
        """把当前失败项目的继续处理意图发给主窗口。"""

        value = self._selected_history_value
        if value is None:
            return
        self.retry_requested.emit(value.project_id, value.processing_mode)

    def _request_delete(self) -> None:
        """确认后提交删除一个或多个视频项目及其工作目录的请求。"""

        targets = self._selected_history_targets()
        if not targets:
            return
        if len(targets) == 1:
            summary = f"任务：{targets[0][2]}"
        else:
            names = "\n".join(f"- {name}" for _pid, _dir, name in targets)
            summary = f"共 {len(targets)} 个任务：\n{names}"
        answer = QMessageBox.question(
            self,
            "确认删除任务",
            "删除后将永久移除这些视频任务的处理记录、字幕、缓存和项目目录。\n\n"
            "正在处理的任务也可以删除，应用会在后台线程退出后再次清理。\n"
            "原始视频和保存到项目目录外的成品不会被删除。\n\n"
            f"{summary}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.delete_requested.emit(
            [
                (project_id, workspace_dir)
                for project_id, workspace_dir, _name in targets
            ]
        )

    def _selected_history_targets(self) -> list[tuple[str, str, str]]:
        """返回当前选中的全部视频任务，保证删除支持批量执行。

        多选时以 `selectedItems()` 为准；没有额外选择时回退到当前项，
        这样单选和批量两种操作都不需要用户额外切换选择模式。
        """

        items = self.task_list.selectedItems() or (
            [self.task_list.currentItem()]
            if self.task_list.currentItem() is not None
            else []
        )
        targets: list[tuple[str, str, str]] = []
        for item in items:
            value = item.data(Qt.ItemDataRole.UserRole)
            if not isinstance(value, VideoTaskHistoryDTO):
                continue
            targets.append(
                (value.project_id, str(value.workspace_dir), value.display_name)
            )
        return targets

    def _request_download(self) -> None:
        """选择下载目录，并把安全的成品路径交给主窗口。

        目录选择发生在用户点击下载之后。页面只负责收集意图和做即时路径
        校验，实际的视频复制或烧录仍由核心服务在后台完成。
        """

        value = self._selected_history_value
        mode_value = self.export_mode_combo.currentData()
        if value is None or not isinstance(mode_value, str):
            return

        selected_directory = QFileDialog.getExistingDirectory(
            self,
            "选择成品下载目录",
            str(self._default_download_directory(value)),
        )
        if not selected_directory:
            return

        # `getExistingDirectory` 正常只返回目录，这里仍保留一次本地校验，
        # 避免测试替身或异常平台返回普通文件后把它当成父目录使用。
        download_directory = Path(selected_directory).resolve()
        if not download_directory.is_dir():
            QMessageBox.warning(
                self,
                "无法下载",
                "请选择存在的下载目录。",
            )
            return

        # 外挂字幕下载的主要成品是 `.srt`，烧录模式才需要生成视频文件。
        # 两种模式都追加“字幕”便于用户在下载目录中辨认结果。
        suffix = (
            ".srt"
            if mode_value == ExportMode.SOFT_SUBTITLE.value
            else (value.source_video.suffix or ".mp4")
        )
        output_path = (
            download_directory
            / f"{value.source_video.stem}-字幕{suffix}"
        )
        if output_path.resolve() == value.source_video.resolve():
            QMessageBox.warning(
                self,
                "无法下载",
                "成品保存路径不能覆盖源视频，请使用其他文件名。",
            )
            return
        output_files = [output_path]
        existing_files = [path for path in output_files if path.exists()]
        if existing_files:
            overwrite = QMessageBox.question(
                self,
                "确认覆盖",
                "下载目录中已有同名成品，是否覆盖？\n"
                + "\n".join(str(path) for path in existing_files),
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if overwrite != QMessageBox.StandardButton.Yes:
                return
        self.download_requested.emit(
            value.project_id,
            mode_value,
            str(output_path),
        )

    @staticmethod
    def _default_download_directory(value: VideoTaskHistoryDTO) -> Path:
        """返回下载目录选择器的建议起点，但不替用户确认保存位置。"""

        if value.output_path is not None:
            return value.output_path.parent
        return value.source_video.parent

    def _prepared_product_ready(self, value: VideoTaskHistoryDTO) -> bool:
        """返回这个任务是否已经有一份可以直接复制出去的烧录成品。

        只有文件此刻仍然存在才算就绪。用户手工删除项目目录里的成品后，
        界面必须回到“需要重新生成”的说法，而不是承诺一次会失败的秒传。
        """

        prepared_path = value.prepared_output_path
        return prepared_path is not None and prepared_path.is_file()

    def _select_export_mode(self, mode_value: str) -> None:
        """让导出模式控件显示项目上次保存的选择。"""

        for index in range(self.export_mode_combo.count()):
            if self.export_mode_combo.itemData(index) == mode_value:
                self.export_mode_combo.setCurrentIndex(index)
                return

    def _sync_project_actions(self) -> None:
        """根据当前项目状态启用恢复与下载操作。

        下载按钮只在这个项目“正在生成成品”时禁用。后台正在识别或翻译其他
        视频不应该让当前项目无法下载，否则用户会看到一个点不动也点不开的
        灰色按钮，只能重启应用。
        """

        value = self._selected_history_value
        available = value is not None
        retryable = available and (
            value.project_status == "failed" or value.task_status == "pending"
        )
        exporting = (
            available and value.project_id in self._exporting_project_ids
        )
        exportable = (
            available
            and not exporting
            and value.processing_mode == "full_pipeline"
            and self._has_complete_translation
        )
        self.retry_button.setEnabled(bool(retryable))
        self.export_mode_combo.setEnabled(
            bool(available and not exporting and value.processing_mode == "full_pipeline")
        )
        self.download_button.setEnabled(bool(exportable))
        # 删除属于项目级清理操作，不受完成、失败或运行状态限制。
        # 运行中删除的最终收尾由主窗口在后台线程退出后完成。
        #
        # 这里必须先算出删除按钮的可用状态，不能放到下面几个 `return` 之后。
        # 下载提示的逻辑对“正在导出”和“成品已生成”两种情况会提前返回，
        # 而这两种情况恰好是已完成任务最常见的状态；一旦被跳过，
        # 删除按钮就会一直停留在构造时的禁用状态，用户会觉得任务删不掉。
        self.delete_button.setEnabled(bool(self._selected_history_targets()))
        if exporting:
            self.download_button.setToolTip("该视频正在生成成品，请等待本次下载结束。")
            return
        if value is not None and self._prepared_product_ready(value):
            self.download_button.setToolTip(
                "成品已在任务目录生成，点击下载会直接保存到所选目录。"
            )
            return
        self.download_button.setToolTip(
            "可重复下载；每次都可以重新选择保存目录。"
        )

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
        enabled = not self._subtitle_action_running
        self.save_translation_button.setEnabled(enabled)
        self.retranslate_button.setEnabled(enabled)
        self.subtitle_feedback_label.setText(
            f"翻译失败：{value.translation_error}"
            if value.translation_error
            else ""
        )

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
        if value is None:
            self.subtitle_feedback_label.setText("请先选择一条字幕。")
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
        if value.translation_error:
            translated_text += f"\n翻译失败：{value.translation_error}"
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

        self.selected_subtitle_label.setText("请选择一条字幕")
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
                    value.display_name,
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
