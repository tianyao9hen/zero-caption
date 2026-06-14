"""设置页占位模块。"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

from config.settings import Settings


class SettingsPage(QWidget):
    """显示当前运行配置的最小视图。"""

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("设置页占位"))
        layout.addWidget(QLabel(f"Language: {settings.language}"))
