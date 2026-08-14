"""运行配置查看页面。

阶段 4 先把当前实际生效的配置以可复制的表单展示出来。
配置文件写入和运行中动态切换会在持久化阶段统一实现，
避免界面修改看似成功但没有影响已装配服务。
"""

from __future__ import annotations

from PySide6.QtWidgets import QFormLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from config.settings import Settings


class SettingsPage(QWidget):
    """显示当前运行配置的最小视图。"""

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.fields: dict[str, QLineEdit] = {}
        form = QFormLayout()
        values = {
            "工作区": settings.workspace_root,
            "ASR 引擎": settings.engine.asr.provider,
            "ASR 模型": settings.engine.asr.model_name,
            "运行设备": settings.engine.asr.device,
            "翻译引擎": settings.engine.translation.provider,
            "翻译模型": settings.engine.translation.model or "未配置",
            "默认目标语言": settings.subtitle.target_language,
            "默认导出模式": settings.engine.export.default_mode.value,
        }
        for name, value in values.items():
            field = QLineEdit(str(value))
            field.setReadOnly(True)
            self.fields[name] = field
            form.addRow(name, field)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addStretch(1)
