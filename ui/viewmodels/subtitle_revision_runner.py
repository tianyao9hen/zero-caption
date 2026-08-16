"""字幕修订后台线程。

本模块属于 UI 支持层，只负责把核心服务调用放到 Qt 工作线程，避免文件写入
或大模型请求阻塞窗口。字幕校验、持久化和翻译规则仍由核心用例负责。
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from core.dto.subtitle_dto import (
    EditSubtitleTranslationInput,
    RetranslateSubtitleInput,
)
from core.services.task_service import TaskService


class SubtitleRevisionRunner(QThread):
    """在后台执行一次手工译文保存或单句重新翻译。"""

    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        task_service: TaskService,
        request: EditSubtitleTranslationInput | RetranslateSubtitleInput,
    ) -> None:
        """保存服务与请求；调用 `start` 后才会执行实际操作。"""

        super().__init__()
        self.task_service = task_service
        self.request = request

    def run(self) -> None:
        """在线程中调用对应核心服务，并用 Qt 信号返回结果或错误。"""

        try:
            if isinstance(self.request, EditSubtitleTranslationInput):
                result = self.task_service.edit_subtitle_translation(self.request)
            else:
                result = self.task_service.retranslate_subtitle(self.request)
        except Exception as exc:
            self.failed.emit(str(exc) or exc.__class__.__name__)
            return
        self.succeeded.emit(result)
