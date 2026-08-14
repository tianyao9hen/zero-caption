"""设置页面单元测试。

这些测试只验证界面输入、密钥遮蔽和信号数据，不访问磁盘或翻译服务。
配置持久化由配置层测试单独保护。
"""

from PySide6.QtWidgets import QApplication, QLineEdit

from config.settings import EngineSettings, Settings, TranslationSettings
from ui.pages.settings_page import SettingsPage


def test_settings_page_masks_key_and_emits_edited_translation_settings(
    monkeypatch,
) -> None:
    """密钥输入应默认遮蔽，点击保存时应发出完整的结构化配置。"""

    # arrange：离屏平台让测试不依赖当前 Windows 桌面是否可见。
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    settings = Settings(
        engine=EngineSettings(
            translation=TranslationSettings(
                base_url="https://old.example/v1",
                model="old-model",
                api_key="old-secret",
            )
        )
    )
    page = SettingsPage(settings)
    emitted: list[TranslationSettings] = []
    page.save_requested.connect(emitted.append)

    # act：模拟用户修改设置并点击保存按钮。
    page.base_url_field.setText("https://new.example/v1")
    page.model_field.setText("new-model")
    page.api_key_field.setText("new-secret")
    page.timeout_spin.setValue(90.0)
    page.retry_spin.setValue(5)
    page.batch_segments_spin.setValue(40)
    page.batch_characters_spin.setValue(8_000)
    page.save_button.click()
    app.processEvents()

    # assert：输入框始终使用密码模式，信号携带的是配置对象而不是散乱字段。
    assert page.api_key_field.echoMode() is QLineEdit.EchoMode.Password
    assert len(emitted) == 1
    assert emitted[0].base_url == "https://new.example/v1"
    assert emitted[0].model == "new-model"
    assert emitted[0].api_key == "new-secret"
    assert emitted[0].timeout_seconds == 90.0
    assert emitted[0].max_retries == 5
    assert emitted[0].max_batch_segments == 40
    assert emitted[0].max_batch_characters == 8_000

    page.deleteLater()
    app.processEvents()
