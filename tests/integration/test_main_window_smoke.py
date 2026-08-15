"""主窗口构造烟测，保护启动装配和页面栈不会在创建时崩溃。"""

import logging

from PySide6.QtWidgets import QApplication

from app.container import AppContainer
from config.settings import EngineSettings, Settings
from core.dto.asr_dto import AsrHardwareInfoDTO
from infrastructure.storage.workspace import WorkspaceManager


def cpu_hardware_info() -> AsrHardwareInfoDTO:
    """让窗口烟测固定走不依赖 GPU 的 `small + CPU` 路径。"""

    return AsrHardwareInfoDTO.cpu_only("测试固定使用 CPU。")


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
        asr_hardware_info=cpu_hardware_info(),
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


def test_main_window_refreshes_task_service_after_translation_settings_save(
    tmp_path,
    monkeypatch,
) -> None:
    """保存大模型设置后，后续任务应使用容器重新装配的新服务。"""

    # arrange：用临时写入函数截获设置，避免测试修改真实用户目录。
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    workspace = WorkspaceManager(tmp_path / "workspace")
    workspace.ensure_structure()
    saved_settings = []

    def save_to_temporary_file(settings):
        saved_settings.append(settings)
        return tmp_path / "settings.toml"

    monkeypatch.setattr(
        "app.container.save_engine_settings",
        save_to_temporary_file,
    )
    container = AppContainer(
        settings=Settings(workspace_root=workspace.root),
        workspace=workspace,
        logger=logging.getLogger("test-settings-refresh"),
        asr_hardware_info=cpu_hardware_info(),
    )
    window = container.create_main_window()
    original_service = window.task_service

    # act：通过真实页面按钮走完“信号 -> 主窗口 -> 容器 -> 重装配”路径。
    window.settings_page.base_url_field.setText("https://llm.example/v1")
    window.settings_page.model_field.setText("caption-model")
    window.settings_page.api_key_field.setText("configured-secret")
    window.settings_page.system_prompt_field.setPlainText("保存后的新系统提示词")
    window.settings_page.save_button.click()
    app.processEvents()

    # assert：配置已交给持久化入口，窗口和容器同时切换到新配置和新服务。
    assert len(saved_settings) == 1
    assert isinstance(saved_settings[0], EngineSettings)
    assert saved_settings[0].translation.api_key == "configured-secret"
    assert container.settings.engine.translation.model == "caption-model"
    assert container.settings.engine.translation.system_prompt == "保存后的新系统提示词"
    assert window.settings.engine.translation.base_url == "https://llm.example/v1"
    assert window.task_service is not original_service
    assert (
        window.task_service.translate_subtitles_usecase.translator.system_prompt
        == "保存后的新系统提示词"
    )
    assert "后续任务将使用新配置" in window.settings_page.feedback_label.text()

    window.close()
    window.deleteLater()
    app.processEvents()
