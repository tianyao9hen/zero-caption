"""发布版启动探针测试，保护没有真实显示器时的最小启动路径。"""

import logging

from PySide6.QtWidgets import QApplication

from app.container import AppContainer
from config.settings import Settings
from infrastructure.storage.workspace import WorkspaceManager


def test_startup_probe_creates_workspace_database_and_window(tmp_path, monkeypatch) -> None:
    """启动装配应创建 SQLite 文件和可显示的主窗口。"""

    # arrange：离屏 Qt 让测试可以在 CI 或打包机的无桌面环境执行。
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    workspace = WorkspaceManager(tmp_path / "data")
    workspace.ensure_structure()

    # act：复用正式启动装配，而不是测试专用的手工依赖拼接。
    container = AppContainer(
        settings=Settings(workspace_root=workspace.root),
        workspace=workspace,
        logger=logging.getLogger("packaged-startup"),
    )
    window = container.create_main_window()

    # assert：工作区数据库和主窗口都已经就绪。
    assert workspace.database_path.is_file()
    assert window.windowTitle() == "Zero Caption"
    window.close()
    window.deleteLater()
    app.processEvents()
