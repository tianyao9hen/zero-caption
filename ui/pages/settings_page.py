"""应用设置页面。

这个文件属于 UI 层，负责展示本地运行信息并收集用户填写的大模型翻译参数。
页面只发出结构化配置，不直接写文件、创建翻译器或访问网络；持久化和依赖重装配
由 `app` 层完成，从而保持界面层与基础设施层之间的边界。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
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

from config.settings import Settings, TranslationSettings


class SettingsPage(QWidget):
    """显示运行配置，并把大模型设置保存请求交给主窗口处理。"""

    # `Signal` 是 Qt 的事件通知机制。这里传递普通 Python 对象，
    # 让页面只负责收集输入，而不需要知道配置最终写到哪个目录。
    save_requested = Signal(object)

    def __init__(self, settings: Settings) -> None:
        """根据当前生效配置创建只读信息区和可编辑的大模型表单。"""

        super().__init__()
        self.fields: dict[str, QLineEdit] = {}

        content = QWidget()
        content.setMaximumWidth(760)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 16, 20, 20)
        content_layout.setSpacing(14)

        content_layout.addWidget(self._build_runtime_group(settings))
        content_layout.addWidget(self._build_translation_group(settings.engine.translation))
        content_layout.addWidget(self._build_request_group(settings.engine.translation))

        action_layout = QHBoxLayout()
        self.feedback_label = QLabel("")
        self.feedback_label.setMinimumHeight(24)
        self.feedback_label.setWordWrap(True)
        self.save_button = QPushButton("保存大模型设置")
        self.save_button.setObjectName("saveTranslationSettingsButton")
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

    def apply_saved_settings(self, settings: TranslationSettings) -> None:
        """在保存成功后同步表单值，确保页面展示的是实际生效配置。"""

        self._select_provider(settings.provider)
        self.base_url_field.setText(settings.base_url)
        self.model_field.setText(settings.model)
        self.api_key_field.setText(settings.api_key)
        self.api_key_env = settings.api_key_env
        self.timeout_spin.setValue(settings.timeout_seconds)
        self.retry_spin.setValue(settings.max_retries)
        self.batch_segments_spin.setValue(settings.max_batch_segments)
        self.batch_characters_spin.setValue(settings.max_batch_characters)

    def show_save_result(self, success: bool, message: str) -> None:
        """在表单底部显示保存结果，不弹出会打断操作的模态窗口。"""

        color = "#18794e" if success else "#b42318"
        self.feedback_label.setStyleSheet(f"color: {color};")
        self.feedback_label.setText(message)

    def _build_runtime_group(self, settings: Settings) -> QGroupBox:
        """创建只读的本地运行信息分组。"""

        group = QGroupBox("本地运行")
        form = self._new_form_layout()
        values = {
            "工作区": settings.workspace_root,
            "识别引擎": settings.engine.asr.provider,
            "识别模型": settings.engine.asr.model_name,
            "运行设备": settings.engine.asr.device,
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

    def _emit_save_requested(self) -> None:
        """清除旧反馈，并把当前表单值作为保存请求发给主窗口。"""

        self.feedback_label.clear()
        self.save_requested.emit(self.translation_settings())
