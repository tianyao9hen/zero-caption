"""设置页面单元测试。

这些测试只验证界面输入、工作区选择、密钥遮蔽和信号数据，不访问翻译服务。
配置持久化由配置层测试单独保护。
"""

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton

from config.settings import AsrSettings, EngineSettings, Settings, TranslationSettings
from core.dto.asr_dto import AsrHardwareInfoDTO
from ui.pages.settings_page import SettingsPage


def gpu_hardware_info() -> AsrHardwareInfoDTO:
    """返回适合设置页测试的固定 6GB GPU 快照。"""

    return AsrHardwareInfoDTO(
        cuda_available=True,
        device_count=1,
        gpu_name="RTX 4050 Laptop GPU",
        vram_mb=6_141,
        supported_compute_types=("float16", "int8", "int8_float16"),
        recommended_model="medium",
        recommended_device="cuda",
        recommended_compute_type="float16",
        diagnostic_message="推荐 medium + CUDA + float16。",
    )


def test_settings_page_masks_key_and_emits_edited_translation_settings(
    monkeypatch,
) -> None:
    """密钥输入应默认遮蔽，停止编辑后应自动发出完整配置。"""

    # arrange：离屏平台让测试不依赖当前 Windows 桌面是否可见。
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    settings = Settings(
        engine=EngineSettings(
            asr=AsrSettings(),
            translation=TranslationSettings(
                base_url="https://old.example/v1",
                model="old-model",
                api_key="old-secret",
            )
        )
    )
    page = SettingsPage(settings, gpu_hardware_info())
    emitted: list[EngineSettings] = []
    page.save_requested.connect(emitted.append)

    # 设置页首次打开就应展示内置提示词，同时保留普通文本编辑能力。
    assert (
        page.system_prompt_field.toPlainText()
        == TranslationSettings().system_prompt
    )
    assert page.system_prompt_field.isReadOnly() is False

    # act：连续修改多项设置，计时器应只提交用户停止编辑后的最后一份值。
    page.base_url_field.setText("https://new.example/v1")
    page.model_field.setText("new-model")
    page.api_key_field.setText("new-secret")
    page.system_prompt_field.setPlainText("新的系统提示词")
    page.asr_model_combo.setCurrentIndex(page.asr_model_combo.findData("medium"))
    page.asr_device_combo.setCurrentIndex(page.asr_device_combo.findData("cuda"))
    page.asr_compute_combo.setCurrentIndex(
        page.asr_compute_combo.findData("float16")
    )
    page.timeout_spin.setValue(90.0)
    page.retry_spin.setValue(5)
    page.batch_characters_spin.setValue(8_000)
    QTest.qWait(650)

    # assert：输入框始终使用密码模式，信号携带的是配置对象而不是散乱字段。
    assert page.api_key_field.echoMode() is QLineEdit.EchoMode.Password
    assert len(emitted) == 1
    assert emitted[0].asr.model_name == "medium"
    assert emitted[0].asr.device == "cuda"
    assert emitted[0].asr.compute_type == "float16"
    assert emitted[0].translation.base_url == "https://new.example/v1"
    assert emitted[0].translation.model == "new-model"
    assert emitted[0].translation.api_key == "new-secret"
    assert emitted[0].translation.timeout_seconds == 90.0
    assert emitted[0].translation.max_retries == 5
    assert emitted[0].translation.system_prompt == "新的系统提示词"
    assert emitted[0].translation.max_batch_segments == 1
    assert emitted[0].translation.max_batch_characters == 8_000
    assert page.findChild(QPushButton, "saveEngineSettingsButton") is None

    page.deleteLater()
    app.processEvents()


def test_settings_page_applies_detected_gpu_recommendation(monkeypatch) -> None:
    """点击推荐按钮应填入推荐组合，并自动保存最终配置。"""

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    page = SettingsPage(Settings(), gpu_hardware_info())
    emitted: list[EngineSettings] = []
    page.save_requested.connect(emitted.append)

    page.apply_recommendation_button.click()
    QTest.qWait(650)

    assert page.asr_model_combo.currentData() == "medium"
    assert page.asr_device_combo.currentData() == "cuda"
    assert page.asr_compute_combo.currentData() == "float16"
    assert page.cpu_fallback_check.isChecked() is True
    assert len(emitted) == 1
    assert emitted[0].asr.model_name == "medium"
    assert emitted[0].asr.device == "cuda"
    assert emitted[0].asr.compute_type == "float16"
    page.deleteLater()
    app.processEvents()


def test_settings_page_does_not_resave_values_written_back_by_application(
    monkeypatch,
) -> None:
    """应用写回已保存配置时不应再次触发自动保存循环。"""

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    page = SettingsPage(Settings(), gpu_hardware_info())
    emitted: list[EngineSettings] = []
    page.save_requested.connect(emitted.append)

    page.model_field.setText("auto-save-model")
    QTest.qWait(650)
    assert len(emitted) == 1

    # act：模拟主窗口保存成功后把实际生效配置同步回页面。
    page.apply_saved_engine_settings(emitted[0])
    QTest.qWait(650)

    assert len(emitted) == 1
    page.deleteLater()
    app.processEvents()


def test_settings_page_selects_and_emits_workspace_path(
    tmp_path,
    monkeypatch,
) -> None:
    """文件夹选择器应填入路径，点击应用后再发出工作区切换请求。"""

    # arrange：用临时目录替代系统对话框返回值，测试不会真的打开模态窗口。
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    selected_workspace = tmp_path / "selected-workspace"
    selected_workspace.mkdir()
    monkeypatch.setattr(
        "ui.pages.settings_page.QFileDialog.getExistingDirectory",
        lambda *args: str(selected_workspace),
    )
    page = SettingsPage(Settings(), gpu_hardware_info())
    emitted = []
    page.workspace_change_requested.connect(emitted.append)

    # act：选择按钮只填写路径，用户点击“应用”后才真正请求切换。
    page.workspace_browse_button.click()
    assert page.workspace_field.text() == str(selected_workspace)
    assert emitted == []
    page.workspace_apply_button.click()
    app.processEvents()

    # assert：路径输入框允许编辑，信号使用 `Path` 保留明确的路径语义。
    assert page.workspace_field.isReadOnly() is False
    assert emitted == [selected_workspace]
    page.deleteLater()
    app.processEvents()


def test_settings_page_emits_current_form_for_model_test(monkeypatch) -> None:
    """测试按钮应提交未保存的系统提示词和用户提示词，并展示结果。"""

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    page = SettingsPage(Settings(), gpu_hardware_info())
    emitted: list[tuple[TranslationSettings, str]] = []
    page.test_requested.connect(
        lambda settings, prompt: emitted.append((settings, prompt))
    )

    page.system_prompt_field.setPlainText("当前未保存的系统提示词")
    page.test_prompt_field.setPlainText("当前用户提示词")
    page.test_button.click()
    app.processEvents()

    assert len(emitted) == 1
    assert emitted[0][0].system_prompt == "当前未保存的系统提示词"
    assert emitted[0][1] == "当前用户提示词"
    assert page.test_button.isEnabled() is False

    page.show_test_result(True, "模型返回文本")
    assert page.test_button.isEnabled() is True
    assert page.test_result_field.toPlainText() == "模型返回文本"
    page.deleteLater()
    app.processEvents()
