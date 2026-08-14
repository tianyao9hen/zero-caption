"""后台执行完整视频处理流程的 Qt 线程对象。

这个模块属于 UI 支持层。线程对象只负责把核心服务放到后台执行，
不实现导入、识别、翻译或导出规则；规则仍由 `TaskService` 维护。
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from core.dto.pipeline_dto import ProcessVideoInput
from core.services.task_service import TaskService


class PipelineRunner(QThread):
    """在后台线程执行一次完整的核心视频处理请求。"""

    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, task_service: TaskService, request: ProcessVideoInput) -> None:
        """保存服务和请求，线程启动后才真正执行耗时工作。"""

        super().__init__()
        self.task_service = task_service
        self.request = request

    def run(self) -> None:
        """在线程上下文中调用核心服务，并把结果转成 Qt 信号。"""

        try:
            result = self.task_service.process_video(self.request)
        except Exception as exc:
            self.failed.emit(str(exc) or exc.__class__.__name__)
            return
        self.succeeded.emit(result)
