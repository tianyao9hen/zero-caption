"""应用设置页面。

这个文件属于 UI 层，负责展示硬件能力，并收集本地识别与大模型翻译参数。
页面只发出结构化配置，不直接探测显卡、写文件、创建引擎或访问网络；
持久化和依赖重装配由 `app` 层完成，从而保持分层边界。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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
        content_layout.setContentsMargins(20, 16, 20, 20)
        content_layout.setSpacing(14)

        content_layout.addWidget(self._build_runtime_group(settings, asr_hardware_info))
        content_layout.addWidget(self._build_asr_group(settings.engine.asr))
        content_layout.addWidget(self._build_translation_group(settings.engine.translation))
        content_layout.addWidget(self._build_request_group(settings.engine.translation))

        action_layout = QHBoxLayout()
        self.feedback_label = QLabel("")
        self.feedback_label.setMinimumHeight(24)
        self.feedback_label.setWordWrap(True)
        self.save_button = QPushButton("保存引擎设置")
        self.save_button.setObjectName("saveEngineSettingsButton")
        self.save_button.setMinimumWidth(150)
        self.save_button.clicked.connect(self._emit_save_requested)
        action_layout.addWidget(self.feedback_label, 1)
        action_layout.addWidget(self.save_button)
        content_layout.addLayout(action_layout)
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

    def apply_saved_engine_settings(self, settings: EngineSettings) -> None:
        """保存成功后同步表单，确保展示的是实际生效配置。"""

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
        self.timeout_spin.setValue(settings.translation.timeout_seconds)
        self.retry_spin.setValue(settings.translation.max_retries)
        self.batch_segments_spin.setValue(settings.translation.max_batch_segments)
        self.batch_characters_spin.setValue(settings.translation.max_batch_characters)

    def show_save_result(self, success: bool, message: str) -> None:
        """在表单底部显示保存结果，不弹出会打断操作的模态窗口。"""

        color = "#18794e" if success else "#b42318"
        self.feedback_label.setStyleSheet(f"color: {color};")
        self.feedback_label.setText(message)

    def _build_runtime_group(
        self,
        settings: Settings,
        hardware_info: AsrHardwareInfoDTO,
    ) -> QGroupBox:
        """创建只读的本地运行信息分组。"""

        group = QGroupBox("本地运行")
        form = self._new_form_layout()
        values = {
            "工作区": settings.workspace_root,
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
        self.batch_segments_spin.setRange(1, 200)
        self.batch_segments_spin.setValue(settings.max_batch_segments)

        self.batch_characters_spin = QSpinBox()
        self.batch_characters_spin.setObjectName("translationBatchCharactersSpin")
        self.batch_characters_spin.setRange(100, 100_000)
        self.batch_characters_spin.setSingleStep(500)
        self.batch_characters_spin.setValue(settings.max_batch_characters)

        form.addRow("请求超时", self.timeout_spin)
        form.addRow("失败重试", self.retry_spin)
        form.addRow("单批字幕条数", self.batch_segments_spin)
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
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
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
        """把硬件探测给出的推荐组合填入表单，等待用户保存。"""

        hardware = self.asr_hardware_info
        self._select_combo_data(self.asr_model_combo, hardware.recommended_model)
        self._select_combo_data(self.asr_device_combo, hardware.recommended_device)
        self._select_combo_data(
            self.asr_compute_combo,
            hardware.recommended_compute_type,
        )
        self.cpu_fallback_check.setChecked(True)
        self.feedback_label.setStyleSheet("color: #315a8a;")
        self.feedback_label.setText("已应用推荐值，点击“保存引擎设置”后生效。")

    def _sync_asr_compute_selection(self) -> None:
        """CPU 模式下把不受支持的半精度组合规整为 `int8`。"""

        if (
            self.asr_device_combo.currentData() == "cpu"
            and self.asr_compute_combo.currentData() in {"float16", "int8_float16"}
        ):
            self._select_combo_data(self.asr_compute_combo, "int8")

    def _emit_save_requested(self) -> None:
        """清除旧反馈，并把当前表单值作为保存请求发给主窗口。"""

        self.feedback_label.clear()
        self.save_requested.emit(self.engine_settings())
