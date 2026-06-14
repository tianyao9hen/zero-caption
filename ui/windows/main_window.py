"""主应用窗口模块。

这个文件属于界面层，负责组装控件并把用户操作连接到服务层。
它不应该直接实现媒体处理或其他重型业务逻辑。
"""

from __future__ import annotations

import logging

from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QHBoxLayout,
    QStackedWidget,
)

from config.settings import Settings
from core.services.task_service import TaskService
from infrastructure.storage.workspace import WorkspaceManager
from ui.dialogs.import_dialog import ImportDialog
from ui.pages.projects_page import ProjectsPage
from ui.pages.settings_page import SettingsPage
from ui.pages.tasks_page import TasksPage
from ui.widgets.navigation import NavigationWidget
from ui.widgets.status_bar import StatusBarWidget


class MainWindow(QMainWindow):
    """承载导航、页面和状态栏的顶层窗口。"""

    def __init__(
        self,
        settings: Settings,
        workspace: WorkspaceManager,
        task_service: TaskService,
        logger: logging.Logger,
    ) -> None:
        """创建主窗口，并把子控件之间的关系连接起来。"""

        super().__init__()
        self.settings = settings
        self.workspace = workspace
        self.task_service = task_service
        self.logger = logger
        self.setWindowTitle(settings.app_name)
        self.resize(1200, 800)

        # 这些控件都会随着主窗口长期存在，并由整个窗口共享。
        self.navigation = NavigationWidget()
        self.stack = QStackedWidget()
        self.projects_page = ProjectsPage(workspace=workspace, task_service=task_service)
        self.tasks_page = TasksPage(task_service=task_service)
        self.settings_page = SettingsPage(settings=settings)
        self.status_widget = StatusBarWidget(task_service=task_service)

        # `QStackedWidget` 一次只显示一个页面，但会把其他页面对象也保留在内存里。
        # 对这种小型桌面工具来说，这是一个足够简单直接的页面切换方案。
        self.stack.addWidget(self.projects_page)
        self.stack.addWidget(self.tasks_page)
        self.stack.addWidget(self.settings_page)

        # 界面框架里的信号机制是内建事件机制。
        # 这里导航控件发出页面索引，页面栈据此切换到对应页。
        self.navigation.page_changed.connect(self.stack.setCurrentIndex)

        root = QWidget()
        layout = QVBoxLayout(root)

        # 顶部区域放全局操作，这些按钮不应该随着页面切换而消失。
        header = QHBoxLayout()
        title = QLabel("Zero Caption")
        import_button = QPushButton("导入视频")
        import_button.clicked.connect(self.open_import_dialog)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(import_button)

        layout.addLayout(header)
        layout.addWidget(self.navigation)
        layout.addWidget(self.stack, 1)
        layout.addWidget(self.status_widget)
        self.setCentralWidget(root)

    def open_import_dialog(self) -> None:
        """以模态方式打开导入对话框占位实现。"""

        # `exec()` 会为对话框启动一个局部事件循环，并阻塞父窗口，
        # 直到用户关闭对话框。这种方式适合“小表单先完成再返回主界面”的场景。
        dialog = ImportDialog(self)
        dialog.exec()
