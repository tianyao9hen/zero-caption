"""导入对话框占位模块。

未来真实的项目导入流程会在这里收集源视频路径和相关选项。
当前版本只用它来展示预期的 UI 入口位置。
"""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QDialogButtonBox


class ImportDialog(QDialog):
    """用于启动未来导入流程的模态对话框。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("导入视频")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("导入对话框占位"))

        # `QDialogButtonBox` 可以直接提供符合界面框架习惯的按钮布局和行为。
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
