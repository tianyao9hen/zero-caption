"""设置页面单元测试。

这些测试只验证界面输入、密钥遮蔽和信号数据，不访问磁盘或翻译服务。
配置持久化由配置层测试单独保护。
"""

from PySide6.QtWidgets import QApplication, QLineEdit

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
    """密钥输入应默认遮蔽，点击保存时应发出完整的结构化配置。"""

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

    # act：模拟用户修改设置并点击保存按钮。
    page.base_url_field.setText("https://new.example/v1")
    page.model_field.setText("new-model")
    page.api_key_field.setText("new-secret")
    page.asr_model_combo.setCurrentIndex(page.asr_model_combo.findData("medium"))
    page.asr_device_combo.setCurrentIndex(page.asr_device_combo.findData("cuda"))
    page.asr_compute_combo.setCurrentIndex(
        page.asr_compute_combo.findData("float16")
    )
    page.timeout_spin.setValue(90.0)
    page.retry_spin.setValue(5)
    page.batch_segments_spin.setValue(40)
    page.batch_characters_spin.setValue(8_000)
    page.save_button.click()
    app.processEvents()

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
    assert emitted[0].translation.max_batch_segments == 40
    assert emitted[0].translation.max_batch_characters == 8_000

    page.deleteLater()
    app.processEvents()


def test_settings_page_applies_detected_gpu_recommendation(monkeypatch) -> None:
    """点击推荐按钮应填入 `medium + CUDA + float16`，但不会自动保存。"""

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    page = SettingsPage(Settings(), gpu_hardware_info())
    emitted: list[EngineSettings] = []
    page.save_requested.connect(emitted.append)

    page.apply_recommendation_button.click()
    app.processEvents()

    assert page.asr_model_combo.currentData() == "medium"
    assert page.asr_device_combo.currentData() == "cuda"
    assert page.asr_compute_combo.currentData() == "float16"
    assert page.cpu_fallback_check.isChecked() is True
    assert emitted == []
    page.deleteLater()
    app.processEvents()
