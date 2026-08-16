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
        default_output_directory: str | Path | None = None,
    ) -> None:
        """创建导入表单，并根据翻译配置选择安全的默认处理方式。

        `default_output_directory` 是应用建议的成果目录，用户仍可在表单中
        浏览或手工修改。对话框只计算目标路径，不负责创建目录或写文件。
        """

        super().__init__(parent)
        self.setWindowTitle("创建视频处理任务")
        self.resize(760, 410)

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

        self.output_directory_edit = QLineEdit()
        self.output_directory_edit.setObjectName("resultOutputDirectoryField")
        self.output_directory_edit.setPlaceholderText("选择新生成成果的保存目录")
        if default_output_directory is not None:
            self.output_directory_edit.setText(str(default_output_directory))
        self.output_directory_button = QPushButton("浏览...")
        self.output_directory_button.setObjectName("browseResultOutputDirectoryButton")
        self.output_directory_button.clicked.connect(
            self._browse_output_directory
        )
        output_directory_row = QHBoxLayout()
        output_directory_row.addWidget(self.output_directory_edit, 1)
        output_directory_row.addWidget(self.output_directory_button)

        self.output_preview_label = QLabel()
        self.output_preview_label.setObjectName("resultOutputPreviewLabel")
        self.output_preview_label.setWordWrap(True)

        self.asr_runtime_label = QLabel(
            asr_runtime_summary or "请在设置页选择识别模型和 CPU/GPU 模式"
        )
        self.asr_runtime_label.setWordWrap(True)

        self.processing_hint_label = QLabel()
        self.processing_hint_label.setWordWrap(True)
        self.processing_mode_combo.currentIndexChanged.connect(
            self._sync_processing_controls
        )
        self.export_mode_combo.currentIndexChanged.connect(
            self._sync_output_preview
        )
        self.video_edit.textChanged.connect(self._sync_output_preview)
        self.output_directory_edit.textChanged.connect(
            self._sync_output_preview
        )
        self._sync_processing_controls()

        form = QFormLayout()
        form.addRow(QLabel("视频文件"), video_row)
        form.addRow(QLabel("任务类型"), self.processing_mode_combo)
        form.addRow(QLabel("源语言"), self.source_language_combo)
        form.addRow(QLabel("目标语言"), self.target_language_combo)
        form.addRow(QLabel("导出模式"), self.export_mode_combo)
        form.addRow(QLabel("翻译上下文"), self.context_edit)
        form.addRow(QLabel("成果保存目录"), output_directory_row)
        form.addRow(QLabel("将生成"), self.output_preview_label)
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
            if not self.output_directory_edit.text().strip():
                self.output_directory_edit.setText(
                    str(Path(selected_path).parent)
                )

    def _browse_output_directory(self) -> None:
        """打开目录选择器，让用户决定新成果文件保存在哪里。"""

        initial_directory = self.output_directory_edit.text().strip()
        if not initial_directory:
            source_text = self.video_edit.text().strip()
            initial_directory = (
                str(Path(source_text).parent) if source_text else ""
            )
        selected_directory = QFileDialog.getExistingDirectory(
            self,
            "选择成果保存目录",
            initial_directory,
        )
        if selected_directory:
            self.output_directory_edit.setText(selected_directory)

    def _accept_form(self) -> None:
        """校验必填视频路径后接受对话框。"""

        source_path = Path(self.video_edit.text().strip())
        if not source_path.is_file():
            QMessageBox.warning(self, "无法导入", "请选择存在的本地视频文件。")
            return

        output_directory_text = self.output_directory_edit.text().strip()
        if not output_directory_text:
            QMessageBox.warning(self, "无法创建任务", "请选择成果保存目录。")
            return
        output_directory = Path(output_directory_text).resolve()
        if output_directory.exists() and not output_directory.is_dir():
            QMessageBox.warning(
                self,
                "无法创建任务",
                "成果保存位置必须是目录，不能是已有文件。",
            )
            return

        output_path = self.output_path()
        if output_path is None:
            QMessageBox.warning(self, "无法创建任务", "无法生成成果文件路径。")
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
        self._sync_output_preview()

    def output_path(self) -> Path | None:
        """根据任务类型返回用户可见主要成果的完整路径。

        仅识别任务生成与源视频同名的 `.srt`；完整流程为了避免覆盖
        源视频，会在文件名后增加“字幕”。外挂模式还会由导出器在同一
        目录生成同名 `.srt` 文件。
        """

        source_text = self.video_edit.text().strip()
        output_directory_text = self.output_directory_edit.text().strip()
        if not source_text or not output_directory_text:
            return None

        source_path = Path(source_text)
        # `resolve()` 会把用户手工输入的相对目录转换成明确绝对路径。
        # 这样后台线程不依赖应用从哪个工作目录启动。
        output_directory = Path(output_directory_text).resolve()
        processing_mode = ProcessingMode(
            self.processing_mode_combo.currentData()
        )
        if processing_mode is ProcessingMode.TRANSCRIBE_ONLY:
            return output_directory / f"{source_path.stem}.srt"

        suffix = source_path.suffix or ".mp4"
        return output_directory / f"{source_path.stem}-字幕{suffix}"

    def _sync_output_preview(self) -> None:
        """实时展示将写出的用户成果，避免目录选择含义不清。"""

        output_path = self.output_path()
        if output_path is None:
            self.output_preview_label.setText("选择视频和保存目录后显示成果路径")
            return

        processing_mode = ProcessingMode(
            self.processing_mode_combo.currentData()
        )
        if processing_mode is ProcessingMode.TRANSCRIBE_ONLY:
            self.output_preview_label.setText(str(output_path))
            return

        export_mode = ExportMode(self.export_mode_combo.currentData())
        if export_mode is ExportMode.SOFT_SUBTITLE:
            self.output_preview_label.setText(
                f"视频：{output_path}\n字幕：{output_path.with_suffix('.srt')}"
            )
        else:
            self.output_preview_label.setText(f"烧录字幕视频：{output_path}")

    def to_request(self, workspace_dir: Path) -> ProcessVideoInput:
        """把已确认表单转换成核心层处理请求。"""

        context = self.context_edit.text().strip() or None
        return ProcessVideoInput(
            source_video=Path(self.video_edit.text().strip()),
            source_language=self.source_language_combo.currentText(),
            target_language=self.target_language_combo.currentText(),
            workspace_dir=workspace_dir,
            context=context,
            output_path=self.output_path(),
            export_mode=ExportMode(self.export_mode_combo.currentData()),
            processing_mode=ProcessingMode(
                self.processing_mode_combo.currentData()
            ),
        )
