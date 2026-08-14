"""发布版启动探针测试，保护没有真实显示器时的最小启动路径。"""

import logging
import json

from PySide6.QtWidgets import QApplication

from app.container import AppContainer
from app.main import _run_self_test
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


def test_release_self_test_writes_runtime_report(tmp_path, monkeypatch) -> None:
    """发布自检入口应能在无控制台模式下写出结构化运行报告。"""

    # arrange：把用户数据重定向到临时目录，避免自检污染真实应用目录。
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-app-data"))
    report_path = tmp_path / "self-test.json"

    # act：不加载真实模型，只验证发布自检的装配、路径和报告输出。
    exit_code = _run_self_test(report_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))

    # assert：内置媒体工具和 ASR 模型路径应可被报告识别，翻译未配置只给警告。
    assert exit_code == 0
    assert report["status"] == "warn"
    assert {item["name"] for item in report["items"]} >= {
        "ffmpeg",
        "ffprobe",
        "asr_model",
        "model_cache_dir",
    }
