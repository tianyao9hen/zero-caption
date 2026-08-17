"""应用设置页面。

这个文件属于 UI 层，负责展示硬件能力，并收集本地识别与大模型翻译参数。
页面只发出结构化配置，不直接探测显卡、写文件、创建引擎或访问网络；
持久化和依赖重装配由 `app` 层完成，从而保持分层边界。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from config.settings import AsrSettings, EngineSettings, Settings, TranslationSettings
from core.dto.asr_dto import AsrHardwareInfoDTO


class SettingsPage(QWidget):
    """显示运行能力，并把用户选择的引擎设置交给主窗口处理。"""

    # `Signal` 是 Qt 的事件通知机制。这里传递普通 Python 对象，
    # 让页面只负责收集输入，而不需要知道配置最终写到哪个目录。
    save_requested = Signal(object)
    workspace_change_requested = Signal(object)
    test_requested = Signal(object, str)

    def __init__(
        self,
        settings: Settings,
        asr_hardware_info: AsrHardwareInfoDTO,
    ) -> None:
        """根据当前配置和硬件快照创建可编辑引擎表单。"""

        super().__init__()
        self.fields: dict[str, QLineEdit] = {}
        self.asr_hardware_info = asr_hardware_info
        self.export_settings = settings.engine.export
        self.bundled_models = settings.engine.asr.bundled_models

        content = QWidget()
        content.setMaximumWidth(760)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(12, 8, 12, 12)
        content_layout.setSpacing(8)

        content_layout.addWidget(self._build_runtime_group(settings, asr_hardware_info))
        content_layout.addWidget(self._build_asr_group(settings.engine.asr))
        content_layout.addWidget(self._build_translation_group(settings.engine.translation))
        content_layout.addWidget(self._build_prompt_group(settings.engine.translation))
        content_layout.addWidget(self._build_model_test_group())
        content_layout.addWidget(self._build_request_group(settings.engine.translation))

        # 引擎设置使用短延迟自动保存。文本输入会连续触发很多次变化，
        # 单次计时器只在用户停止编辑后提交最后一份完整配置，避免每输入
        # 一个字符就重写配置文件和重新装配服务。
        self._applying_saved_settings = False
        self._auto_save_timer = QTimer(self)
        self._auto_save_timer.setSingleShot(True)
        self._auto_save_timer.setInterval(500)
        self._auto_save_timer.timeout.connect(self._emit_save_requested)
        self._connect_auto_save_signals()

        self.feedback_label = QLabel("")
        self.feedback_label.setMinimumHeight(24)
        self.feedback_label.setWordWrap(True)
        self.feedback_label.setText("修改引擎设置后会自动保存。")
        content_layout.addWidget(self.feedback_label)
        content_layout.addStretch(1)

        # 设置项在较小窗口中可能超过可用高度，滚动区域可以保持表单不互相挤压。
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll_area.setWidget(content)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll_area)

    def asr_settings(self) -> AsrSettings:
        """读取本地字幕识别表单并返回结构化配置。"""

        return AsrSettings(
            provider="faster-whisper",
            model_name=str(self.asr_model_combo.currentData()),
            device=str(self.asr_device_combo.currentData()),
            compute_type=str(self.asr_compute_combo.currentData()),
            bundled_models=self.bundled_models,
            allow_cpu_fallback=self.cpu_fallback_check.isChecked(),
        )

    def translation_settings(self) -> TranslationSettings:
        """读取表单并返回新的翻译配置，不修改页面外部状态。"""

        return TranslationSettings(
            provider=str(self.provider_combo.currentData()),
            base_url=self.base_url_field.text().strip(),
            model=self.model_field.text().strip(),
            api_key=self.api_key_field.text().strip(),
            api_key_env=self.api_key_env,
            system_prompt=self.system_prompt_field.toPlainText().strip(),
            timeout_seconds=self.timeout_spin.value(),
            max_retries=self.retry_spin.value(),
            max_batch_segments=self.batch_segments_spin.value(),
            max_batch_characters=self.batch_characters_spin.value(),
        )

    def engine_settings(self) -> EngineSettings:
        """汇总本地识别、翻译和现有导出设置。"""

        return EngineSettings(
            asr=self.asr_settings(),
            translation=self.translation_settings(),
            export=self.export_settings,
        )

    def workspace_path(self) -> Path:
        """读取用户填写的工作区路径；空值会作为输入错误报告。"""

        value = self.workspace_field.text().strip()
        if not value:
            raise ValueError("工作区路径不能为空。")
        return Path(value).expanduser()

    def apply_saved_workspace(self, workspace_root: str | Path) -> None:
        """工作区切换成功后，把实际生效的绝对路径同步回输入框。"""

        self.workspace_field.setText(str(workspace_root))

    def apply_saved_engine_settings(self, settings: EngineSettings) -> None:
        """保存成功后同步表单，确保展示的是实际生效配置。"""

        # 主窗口保存成功后会把实际配置写回控件。写回期间暂时忽略控件信号，
        # 否则程序自己的同步动作会再次启动计时器，形成重复保存循环。
        self._applying_saved_settings = True
        try:
            self._select_combo_data(self.asr_model_combo, settings.asr.model_name)
            self._select_combo_data(self.asr_device_combo, settings.asr.device)
            self._select_combo_data(self.asr_compute_combo, settings.asr.compute_type)
            self.cpu_fallback_check.setChecked(settings.asr.allow_cpu_fallback)
            self._sync_asr_compute_selection()
            self._select_provider(settings.translation.provider)
            self.base_url_field.setText(settings.translation.base_url)
            self.model_field.setText(settings.translation.model)
            self.api_key_field.setText(settings.translation.api_key)
            self.api_key_env = settings.translation.api_key_env
            self.system_prompt_field.setPlainText(settings.translation.system_prompt)
            self.timeout_spin.setValue(settings.translation.timeout_seconds)
            self.retry_spin.setValue(settings.translation.max_retries)
            self.batch_segments_spin.setValue(settings.translation.max_batch_segments)
            self.batch_characters_spin.setValue(settings.translation.max_batch_characters)
        finally:
            self._applying_saved_settings = False

    def show_save_result(self, success: bool, message: str) -> None:
        """在表单底部显示保存结果，不弹出会打断操作的模态窗口。"""

        color = "#18794e" if success else "#b42318"
        self.feedback_label.setStyleSheet(f"color: {color};")
        self.feedback_label.setText(message)

    def show_test_result(self, success: bool, message: str) -> None:
        """结束测试状态，并在页面内展示模型返回或错误信息。"""

        color = "#18794e" if success else "#b42318"
        self.test_result_field.setStyleSheet(f"color: {color};")
        self.test_result_field.setPlainText(message)
        self.test_button.setEnabled(True)

    def _build_runtime_group(
        self,
        settings: Settings,
        hardware_info: AsrHardwareInfoDTO,
    ) -> QGroupBox:
        """创建可选择工作区以及只读运行能力信息的分组。"""

        group = QGroupBox("本地运行")
        form = self._new_form_layout()

        # 工作区是本组唯一可编辑的运行设置。输入框允许粘贴路径，
        # “选择文件夹”按钮为不熟悉 Windows 路径的用户提供原生目录选择器。
        self.workspace_field = QLineEdit(str(settings.workspace_root))
        self.workspace_field.setObjectName("workspacePathField")
        self.workspace_field.setClearButtonEnabled(True)
        self.workspace_field.setPlaceholderText("请选择用于保存项目数据的文件夹")
        self.workspace_field.returnPressed.connect(
            self._emit_workspace_change_requested
        )
        self.fields["工作区"] = self.workspace_field

        self.workspace_browse_button = QPushButton("选择文件夹")
        self.workspace_browse_button.setObjectName("browseWorkspaceButton")
        self.workspace_browse_button.clicked.connect(self._browse_workspace)

        self.workspace_apply_button = QPushButton("应用")
        self.workspace_apply_button.setObjectName("applyWorkspaceButton")
        self.workspace_apply_button.clicked.connect(
            self._emit_workspace_change_requested
        )

        workspace_layout = QHBoxLayout()
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.addWidget(self.workspace_field, 1)
        workspace_layout.addWidget(self.workspace_browse_button)
        workspace_layout.addWidget(self.workspace_apply_button)
        form.addRow("工作区", workspace_layout)

        values = {
            "识别引擎": settings.engine.asr.provider,
            "CUDA 状态": "可用" if hardware_info.cuda_available else "不可用",
            "显卡": hardware_info.gpu_name,
            "显存": (
                f"{hardware_info.vram_mb} MB"
                if hardware_info.vram_mb is not None
                else "未知"
            ),
            "内置模型": "、".join(settings.engine.asr.bundled_models),
            "默认目标语言": settings.subtitle.target_language,
            "默认导出模式": settings.engine.export.default_mode.value,
        }
        for name, value in values.items():
            field = QLineEdit(str(value))
            field.setReadOnly(True)
            self.fields[name] = field
            form.addRow(name, field)
        group.setLayout(form)
        return group

    def _browse_workspace(self) -> None:
        """打开系统文件夹选择器，并把选中目录填入工作区输入框。"""

        current_value = self.workspace_field.text().strip()
        start_path = Path(current_value).expanduser() if current_value else Path.home()
        if not start_path.is_dir():
            start_path = start_path.parent

        selected = QFileDialog.getExistingDirectory(
            self,
            "选择 Zero Caption 工作区",
            str(start_path),
            QFileDialog.Option.ShowDirsOnly,
        )
        if selected:
            self.workspace_field.setText(selected)

    def _emit_workspace_change_requested(self) -> None:
        """校验工作区输入，并把切换动作交给主窗口编排。"""

        try:
            workspace_root = self.workspace_path()
        except ValueError as exc:
            self.show_save_result(False, str(exc))
            return
        self.feedback_label.clear()
        self.workspace_change_requested.emit(workspace_root)

    def _build_asr_group(self, settings: AsrSettings) -> QGroupBox:
        """创建本地识别模型、设备、精度和回退设置。"""

        group = QGroupBox("本地字幕识别")
        form = self._new_form_layout()

        self.asr_model_combo = QComboBox()
        self.asr_model_combo.setObjectName("asrModelCombo")
        self.asr_model_combo.addItem("自动（按硬件推荐）", "auto")
        model_labels = {
            "small": "small（兼容模式）",
            "medium": "medium（高质量，推荐）",
        }
        for model_name in self.bundled_models:
            self.asr_model_combo.addItem(
                model_labels.get(model_name, model_name),
                model_name,
            )

        self.asr_device_combo = QComboBox()
        self.asr_device_combo.setObjectName("asrDeviceCombo")
        self.asr_device_combo.addItem("自动（优先可用 GPU）", "auto")
        self.asr_device_combo.addItem("CPU", "cpu")
        cuda_label = "NVIDIA GPU（CUDA）"
        if not self.asr_hardware_info.cuda_available:
            cuda_label += "（当前不可用）"
        self.asr_device_combo.addItem(cuda_label, "cuda")

        self.asr_compute_combo = QComboBox()
        self.asr_compute_combo.setObjectName("asrComputeCombo")
        self.asr_compute_combo.addItem("自动（推荐）", "auto")
        self.asr_compute_combo.addItem("float16（GPU 质量优先）", "float16")
        self.asr_compute_combo.addItem("int8_float16（GPU 省显存）", "int8_float16")
        self.asr_compute_combo.addItem("int8（CPU 省内存）", "int8")
        self.asr_device_combo.currentIndexChanged.connect(
            self._sync_asr_compute_selection
        )

        self.cpu_fallback_check = QCheckBox("GPU 失败时自动切换到 CPU")
        self.cpu_fallback_check.setObjectName("asrCpuFallbackCheck")

        self.apply_recommendation_button = QPushButton("应用硬件推荐")
        self.apply_recommendation_button.setObjectName("applyAsrRecommendationButton")
        self.apply_recommendation_button.clicked.connect(
            self._apply_asr_recommendation
        )
        self.asr_recommendation_label = QLabel(
            self.asr_hardware_info.diagnostic_message
        )
        self.asr_recommendation_label.setWordWrap(True)

        self._select_combo_data(self.asr_model_combo, settings.model_name)
        self._select_combo_data(self.asr_device_combo, settings.device)
        self._select_combo_data(self.asr_compute_combo, settings.compute_type)
        self.cpu_fallback_check.setChecked(settings.allow_cpu_fallback)
        self._sync_asr_compute_selection()

        form.addRow("识别模型", self.asr_model_combo)
        form.addRow("运行设备", self.asr_device_combo)
        form.addRow("推理精度", self.asr_compute_combo)
        form.addRow("失败回退", self.cpu_fallback_check)
        form.addRow("推荐操作", self.apply_recommendation_button)
        form.addRow("硬件建议", self.asr_recommendation_label)
        group.setLayout(form)
        return group

    def _build_translation_group(self, settings: TranslationSettings) -> QGroupBox:
        """创建接口地址、模型和密钥编辑分组。"""

        group = QGroupBox("大模型翻译")
        form = self._new_form_layout()

        self.provider_combo = QComboBox()
        self.provider_combo.setObjectName("translationProviderCombo")
        self.provider_combo.addItem("OpenAI 兼容接口", "openai-compatible")
        self._select_provider(settings.provider)

        self.base_url_field = QLineEdit(settings.base_url)
        self.base_url_field.setObjectName("translationBaseUrlField")
        self.base_url_field.setPlaceholderText("https://api.example.com/v1")
        self.base_url_field.setClearButtonEnabled(True)

        self.model_field = QLineEdit(settings.model)
        self.model_field.setObjectName("translationModelField")
        self.model_field.setPlaceholderText("模型名称")
        self.model_field.setClearButtonEnabled(True)

        self.api_key_field = QLineEdit(settings.api_key)
        self.api_key_field.setObjectName("translationApiKeyField")
        self.api_key_field.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_field.setClearButtonEnabled(True)
        self.api_key_env = settings.api_key_env

        form.addRow("接口类型", self.provider_combo)
        form.addRow("接口地址", self.base_url_field)
        form.addRow("模型名称", self.model_field)
        form.addRow("API 密钥", self.api_key_field)
        group.setLayout(form)
        return group

    def _build_prompt_group(self, settings: TranslationSettings) -> QGroupBox:
        """创建可持久化的翻译系统提示词编辑区。"""

        group = QGroupBox("翻译系统提示词")
        layout = QVBoxLayout(group)
        description = QLabel(
            "该提示词会在下一次逐句翻译和模型测试时作为 system 消息发送。"
        )
        description.setWordWrap(True)
        self.system_prompt_field = QPlainTextEdit(settings.system_prompt)
        self.system_prompt_field.setObjectName("translationSystemPromptField")
        self.system_prompt_field.setPlaceholderText("输入翻译规则和返回格式要求")
        self.system_prompt_field.setMinimumHeight(88)

        self.reset_system_prompt_button = QPushButton("重置为默认提示词")
        self.reset_system_prompt_button.setObjectName(
            "resetTranslationSystemPromptButton"
        )
        self.reset_system_prompt_button.clicked.connect(self._reset_system_prompt)

        button_layout = QHBoxLayout()
        button_layout.addStretch(1)
        button_layout.addWidget(self.reset_system_prompt_button)
        layout.addWidget(description)
        layout.addWidget(self.system_prompt_field)
        layout.addLayout(button_layout)
        return group

    def _build_model_test_group(self) -> QGroupBox:
        """创建用户提示词输入、测试按钮和结果展示区。"""

        group = QGroupBox("大模型测试")
        layout = QVBoxLayout(group)
        description = QLabel(
            "测试使用当前表单中的接口、模型、密钥和系统提示词，不必先保存。"
        )
        description.setWordWrap(True)
        self.test_prompt_field = QPlainTextEdit()
        self.test_prompt_field.setObjectName("translationTestPromptField")
        self.test_prompt_field.setPlaceholderText(
            "例如：请把 Hello, world! 翻译成简体中文。"
        )
        self.test_prompt_field.setMaximumHeight(72)

        self.test_button = QPushButton("测试当前配置")
        self.test_button.setObjectName("testTranslationModelButton")
        self.test_button.clicked.connect(self._emit_test_requested)

        self.test_result_field = QPlainTextEdit()
        self.test_result_field.setObjectName("translationTestResultField")
        self.test_result_field.setReadOnly(True)
        self.test_result_field.setPlaceholderText("模型返回结果会显示在这里")
        self.test_result_field.setMinimumHeight(72)

        button_layout = QHBoxLayout()
        button_layout.addStretch(1)
        button_layout.addWidget(self.test_button)
        layout.addWidget(description)
        layout.addWidget(QLabel("用户提示词"))
        layout.addWidget(self.test_prompt_field)
        layout.addLayout(button_layout)
        layout.addWidget(QLabel("测试结果"))
        layout.addWidget(self.test_result_field)
        return group

    def _build_request_group(self, settings: TranslationSettings) -> QGroupBox:
        """创建请求超时、重试和批处理边界设置。"""

        group = QGroupBox("请求控制")
        form = self._new_form_layout()

        self.timeout_spin = QDoubleSpinBox()
        self.timeout_spin.setObjectName("translationTimeoutSpin")
        self.timeout_spin.setRange(1.0, 600.0)
        self.timeout_spin.setDecimals(1)
        self.timeout_spin.setSuffix(" 秒")
        self.timeout_spin.setValue(settings.timeout_seconds)

        self.retry_spin = QSpinBox()
        self.retry_spin.setObjectName("translationRetrySpin")
        self.retry_spin.setRange(0, 10)
        self.retry_spin.setValue(settings.max_retries)

        self.batch_segments_spin = QSpinBox()
        self.batch_segments_spin.setObjectName("translationBatchSegmentsSpin")
        self.batch_segments_spin.setRange(1, 1)
        self.batch_segments_spin.setValue(1)
        self.batch_segments_spin.setEnabled(False)
        self.batch_segments_spin.setToolTip("逐句翻译模式固定每次只发送一条字幕。")

        self.batch_characters_spin = QSpinBox()
        self.batch_characters_spin.setObjectName("translationBatchCharactersSpin")
        self.batch_characters_spin.setRange(100, 100_000)
        self.batch_characters_spin.setSingleStep(500)
        self.batch_characters_spin.setValue(settings.max_batch_characters)

        form.addRow("请求超时", self.timeout_spin)
        form.addRow("失败重试", self.retry_spin)
        form.addRow("每次请求字幕数", self.batch_segments_spin)
        form.addRow("单批字幕字符数", self.batch_characters_spin)
        group.setLayout(form)
        return group

    def _new_form_layout(self) -> QFormLayout:
        """创建统一行距和对齐方式的紧凑设置表单。"""

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setLabelAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(6)
        return form

    def _select_provider(self, provider: str) -> None:
        """选中当前提供方；遇到旧配置值时保留显示，避免静默覆盖。"""

        index = self.provider_combo.findData(provider)
        if index < 0:
            self.provider_combo.addItem(provider, provider)
            index = self.provider_combo.count() - 1
        self.provider_combo.setCurrentIndex(index)

    def _select_combo_data(self, combo: QComboBox, value: str) -> None:
        """按稳定数据值选中下拉项，未知值回退到第一项。"""

        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _apply_asr_recommendation(self) -> None:
        """把硬件探测给出的推荐组合填入表单并等待自动保存。"""

        hardware = self.asr_hardware_info
        self._select_combo_data(self.asr_model_combo, hardware.recommended_model)
        self._select_combo_data(self.asr_device_combo, hardware.recommended_device)
        self._select_combo_data(
            self.asr_compute_combo,
            hardware.recommended_compute_type,
        )
        self.cpu_fallback_check.setChecked(True)
        self.feedback_label.setStyleSheet("color: #315a8a;")
        self.feedback_label.setText("已应用推荐值，正在等待自动保存。")

    def _reset_system_prompt(self) -> None:
        """恢复内置翻译提示词，并保留文本框的普通编辑能力。

        默认值来自 `TranslationSettings`，避免设置页复制一份容易过期的提示词。
        `setPlainText` 会触发现有自动保存信号，用户也可以在重置后继续修改内容。
        """

        self.system_prompt_field.setPlainText(TranslationSettings().system_prompt)
        self.system_prompt_field.setFocus()

    def _sync_asr_compute_selection(self) -> None:
        """CPU 模式下把不受支持的半精度组合规整为 `int8`。"""

        if (
            self.asr_device_combo.currentData() == "cpu"
            and self.asr_compute_combo.currentData() in {"float16", "int8_float16"}
        ):
            self._select_combo_data(self.asr_compute_combo, "int8")

    def _connect_auto_save_signals(self) -> None:
        """连接所有引擎编辑控件，在输入停止后统一自动保存。"""

        for combo in (
            self.asr_model_combo,
            self.asr_device_combo,
            self.asr_compute_combo,
            self.provider_combo,
        ):
            combo.currentIndexChanged.connect(self._schedule_auto_save)
        self.cpu_fallback_check.toggled.connect(self._schedule_auto_save)
        for field in (
            self.base_url_field,
            self.model_field,
            self.api_key_field,
        ):
            field.textChanged.connect(self._schedule_auto_save)
        self.system_prompt_field.textChanged.connect(self._schedule_auto_save)
        for spin in (
            self.timeout_spin,
            self.retry_spin,
            self.batch_characters_spin,
        ):
            spin.valueChanged.connect(self._schedule_auto_save)

    def _schedule_auto_save(self, *_args: object) -> None:
        """重启自动保存计时器，只提交用户最后一次编辑后的配置。"""

        if self._applying_saved_settings:
            return
        self.feedback_label.setStyleSheet("color: #315a8a;")
        self.feedback_label.setText("设置已修改，将在输入完成后自动保存……")
        self._auto_save_timer.start()

    def _emit_save_requested(self) -> None:
        """把停止编辑后的当前表单值作为保存请求发给主窗口。"""

        self.feedback_label.clear()
        self.save_requested.emit(self.engine_settings())

    def _emit_test_requested(self) -> None:
        """把当前表单和测试提示词交给主窗口安排后台请求。"""

        prompt = self.test_prompt_field.toPlainText().strip()
        if not prompt:
            self.show_test_result(False, "请输入用于测试模型的用户提示词。")
            return

        self.test_button.setEnabled(False)
        self.test_result_field.setStyleSheet("color: #315a8a;")
        self.test_result_field.setPlainText("正在后台测试，请稍候……")
        self.test_requested.emit(self.translation_settings(), prompt)
