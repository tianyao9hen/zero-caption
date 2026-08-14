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


class ImportDialog(QDialog):
    """收集一次视频处理请求所需的最小参数。"""

    def __init__(self, parent=None, default_source_language: str = "auto", default_target_language: str = "zh-CN") -> None:
        """创建导入表单，并预填充应用默认语言。"""

        super().__init__(parent)
        self.setWindowTitle("导入视频")
        self.resize(620, 240)

        self.video_edit = QLineEdit()
        self.video_edit.setPlaceholderText("选择本地视频文件")
        browse_button = QPushButton("浏览...")
        browse_button.clicked.connect(self._browse_video)
        video_row = QHBoxLayout()
        video_row.addWidget(self.video_edit, 1)
        video_row.addWidget(browse_button)

        self.source_language_combo = QComboBox()
        self.source_language_combo.addItems(["auto", "zh-CN", "en", "ja", "ko"])
        self.source_language_combo.setCurrentText(default_source_language)

        self.target_language_combo = QComboBox()
        self.target_language_combo.addItems(["zh-CN", "en", "ja", "ko"])
        self.target_language_combo.setCurrentText(default_target_language)

        self.context_edit = QLineEdit()
        self.context_edit.setPlaceholderText("可选：作品、术语或角色上下文")

        form = QFormLayout()
        form.addRow(QLabel("视频文件"), video_row)
        form.addRow(QLabel("源语言"), self.source_language_combo)
        form.addRow(QLabel("目标语言"), self.target_language_combo)
        form.addRow(QLabel("翻译上下文"), self.context_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept_form)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _browse_video(self) -> None:
        """打开系统文件选择器，把用户选择的路径填入表单。"""

        selected_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择视频文件",
            "",
            "视频文件 (*.mp4 *.mkv *.mov *.avi *.webm);;所有文件 (*.*)",
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

    def to_request(self, workspace_dir: Path) -> ProcessVideoInput:
        """把已确认表单转换成核心层处理请求。"""

        context = self.context_edit.text().strip() or None
        return ProcessVideoInput(
            source_video=Path(self.video_edit.text().strip()),
            source_language=self.source_language_combo.currentText(),
            target_language=self.target_language_combo.currentText(),
            workspace_dir=workspace_dir,
            context=context,
        )
