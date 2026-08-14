"""主窗口构造烟测，保护启动装配和页面栈不会在创建时崩溃。"""

import logging

from PySide6.QtWidgets import QApplication

from app.container import AppContainer
from config.settings import Settings
from infrastructure.storage.workspace import WorkspaceManager


def test_main_window_can_be_created_offscreen(tmp_path, monkeypatch) -> None:
    """在无显示器环境中创建主窗口，验证 Qt 控件和依赖注入已接通。"""

    # arrange：离屏平台避免测试依赖 Windows 桌面当前显示器。
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    workspace = WorkspaceManager(tmp_path / "workspace")
    workspace.ensure_structure()
    settings = Settings(workspace_root=workspace.root)
    container = AppContainer(
        settings=settings,
        workspace=workspace,
        logger=logging.getLogger("test-main-window"),
    )

    # act：通过容器创建完整主窗口，而不是手工绕过装配层。
    window = container.create_main_window()

    # assert：窗口标题、尺寸和核心页面对象均已创建。
    assert window.windowTitle() == "Zero Caption"
    assert window.size().width() == 1200
    assert window.projects_page is not None
    assert window.tasks_page is not None
    window.close()
    window.deleteLater()
    app.processEvents()
