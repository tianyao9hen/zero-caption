"""大模型配置测试的 Qt 后台线程。

这个模块属于 UI 支持层，只负责把可能阻塞的网络测试放到工作线程。
它不创建翻译适配器，也不实现提示词或认证规则；这些职责仍由应用层和基础设施层承担。
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QThread, Signal

from config.settings import TranslationSettings


class TranslationTestRunner(QThread):
    """在后台执行一次大模型配置测试，并通过 Qt 信号返回结果。"""

    succeeded = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        tester: Callable[[TranslationSettings, str], str],
        settings: TranslationSettings,
        user_prompt: str,
    ) -> None:
        """保存应用层测试入口和表单快照，线程启动后才访问网络。"""

        super().__init__()
        self.tester = tester
        self.settings = settings
        self.user_prompt = user_prompt

    def run(self) -> None:
        """在线程上下文调用应用层入口，并把异常转换成界面信号。"""

        try:
            result = self.tester(self.settings, self.user_prompt)
        except Exception as exc:
            self.failed.emit(str(exc) or exc.__class__.__name__)
            return
        self.succeeded.emit(result)
