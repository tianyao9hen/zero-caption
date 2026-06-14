"""主窗口导航控件模块。

这个控件通过一个很小的基于信号的接口和外部通信，而不是直接控制主窗口。
这样职责更清晰，也更容易复用和理解。
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton


class NavigationWidget(QWidget):
    """横向页面导航按钮组。"""

    # `Signal(int)` 表示这个信号会发出一个整数参数。
    # 在当前骨架里，这个整数就是页面栈控件需要的页面索引。
    page_changed = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        self.projects_button = QPushButton("项目")
        self.tasks_button = QPushButton("任务")
        self.settings_button = QPushButton("设置")
        layout.addWidget(self.projects_button)
        layout.addWidget(self.tasks_button)
        layout.addWidget(self.settings_button)
        layout.addStretch(1)

        # 这里使用匿名函数，只是为了把一个固定页面索引绑定到按钮点击事件上。
        # 如果逻辑再复杂一些，就更适合改成具名方法。
        self.projects_button.clicked.connect(lambda: self.page_changed.emit(0))
        self.tasks_button.clicked.connect(lambda: self.page_changed.emit(1))
        self.settings_button.clicked.connect(lambda: self.page_changed.emit(2))
