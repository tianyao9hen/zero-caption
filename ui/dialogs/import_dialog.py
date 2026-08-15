"""视频导入参数对话框。

这个模块属于 UI 层，只负责收集路径、语言和上下文等用户输入。
点击确认后返回核心层的 `ProcessVideoInput`，不在对话框里执行任何媒体处理。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from core.dto.pipeline_dto import ProcessVideoInput
from core.domain.enums import ExportMode, ProcessingMode


class ImportDialog(QDialog):
    """收集一次视频处理请求所需的最小参数。"""

    def __init__(
        self,
        parent=None,
        default_source_language: str = "auto",
        default_target_language: str = "zh-CN",
        translation_configured: bool = False,
        asr_runtime_summary: str = "",
    ) -> None:
        """创建导入表单，并根据翻译配置选择安全的默认处理方式。"""

        super().__init__(parent)
        self.setWindowTitle("创建视频处理任务")
        self.resize(680, 330)

        self.video_edit = QLineEdit()
        self.video_edit.setPlaceholderText("选择本地视频文件")
        browse_button = QPushButton("浏览...")
        browse_button.clicked.connect(self._browse_video)
        video_row = QHBoxLayout()
        video_row.addWidget(self.video_edit, 1)
        video_row.addWidget(browse_button)

        self.processing_mode_combo = QComboBox()
        self.processing_mode_combo.setObjectName("processingModeCombo")
        self.processing_mode_combo.addItem(
            "自动识别语言并生成原文字幕（本地）",
            ProcessingMode.TRANSCRIBE_ONLY,
        )
        self.processing_mode_combo.addItem(
            "自动识别、逐句翻译并导出",
            ProcessingMode.FULL_PIPELINE,
        )
        if translation_configured:
            self.processing_mode_combo.setCurrentIndex(1)

        self.source_language_combo = QComboBox()
        self.source_language_combo.addItems(["auto", "zh-CN", "en", "ja", "ko"])
        self.source_language_combo.setCurrentText(default_source_language)

        self.target_language_combo = QComboBox()
        self.target_language_combo.addItems(["zh-CN", "en", "ja", "ko"])
        self.target_language_combo.setCurrentText(default_target_language)

        self.export_mode_combo = QComboBox()
        self.export_mode_combo.addItem("外挂字幕（推荐）", ExportMode.SOFT_SUBTITLE)
        self.export_mode_combo.addItem("烧录字幕", ExportMode.BURN_IN)

        self.context_edit = QLineEdit()
        self.context_edit.setPlaceholderText("可选：作品、术语或角色上下文")

        self.asr_runtime_label = QLabel(
            asr_runtime_summary or "请在设置页选择识别模型和 CPU/GPU 模式"
        )
        self.asr_runtime_label.setWordWrap(True)

        self.processing_hint_label = QLabel()
        self.processing_hint_label.setWordWrap(True)
        self.processing_mode_combo.currentIndexChanged.connect(
            self._sync_processing_controls
        )
        self._sync_processing_controls()

        form = QFormLayout()
        form.addRow(QLabel("视频文件"), video_row)
        form.addRow(QLabel("任务类型"), self.processing_mode_combo)
        form.addRow(QLabel("源语言"), self.source_language_combo)
        form.addRow(QLabel("目标语言"), self.target_language_combo)
        form.addRow(QLabel("导出模式"), self.export_mode_combo)
        form.addRow(QLabel("翻译上下文"), self.context_edit)
        form.addRow(QLabel("本次识别配置"), self.asr_runtime_label)
        form.addRow(QLabel("说明"), self.processing_hint_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept_form)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("创建并开始")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _browse_video(self) -> None:
        """打开系统文件选择器，把用户选择的路径填入表单。"""

        selected_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择视频文件",
            "",
            "视频文件 (*.mp4 *.mkv *.mov *.avi *.webm *.flv);;所有文件 (*.*)",
        )
        if selected_path:
            self.video_edit.setText(selected_path)

    def _accept_form(self) -> None:
        """校验必填视频路径后接受对话框。"""

        source_path = Path(self.video_edit.text().strip())
        if not source_path.is_file():
            QMessageBox.warning(self, "无法导入", "请选择存在的本地视频文件。")
            return
        self.accept()

    def _sync_processing_controls(self) -> None:
        """根据处理方式启用翻译相关控件并解释本地模式边界。"""

        processing_mode = ProcessingMode(
            self.processing_mode_combo.currentData()
        )
        full_pipeline = processing_mode is ProcessingMode.FULL_PIPELINE
        self.target_language_combo.setEnabled(full_pipeline)
        self.export_mode_combo.setEnabled(full_pipeline)
        self.context_edit.setEnabled(full_pipeline)
        if full_pipeline:
            self.processing_hint_label.setText(
                "创建后会在后台依次执行识别、逐句翻译和导出；"
                "完整流程需要可用的大模型配置。"
            )
        else:
            self.processing_hint_label.setText(
                "创建后会在后台抽取音频并生成原文字幕；"
                "视频、音频和识别数据不会上传到大模型。"
            )

    def to_request(self, workspace_dir: Path) -> ProcessVideoInput:
        """把已确认表单转换成核心层处理请求。"""

        context = self.context_edit.text().strip() or None
        return ProcessVideoInput(
            source_video=Path(self.video_edit.text().strip()),
            source_language=self.source_language_combo.currentText(),
            target_language=self.target_language_combo.currentText(),
            workspace_dir=workspace_dir,
            context=context,
            export_mode=ExportMode(self.export_mode_combo.currentData()),
            processing_mode=ProcessingMode(
                self.processing_mode_combo.currentData()
            ),
        )
