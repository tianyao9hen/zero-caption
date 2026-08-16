"""后台执行完整视频处理流程的 Qt 线程对象。

这个模块属于 UI 支持层。线程对象只负责把核心服务放到后台执行，
不实现导入、识别、翻译或导出规则；规则仍由 `TaskService` 维护。
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QThread, Signal


class PipelineRunner(QThread):
    """在后台线程执行一次核心层项目操作。

    新建流程、失败恢复和重新导出都会处理大文件或访问外部能力，界面层
    通过这个统一线程适配器执行它们。具体业务操作仍由调用方传入的核心
    服务方法完成，本类只负责线程切换和结果信号。
    """

    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, operation: Callable[[], object]) -> None:
        """保存一个无参数核心操作，线程启动后才真正调用。"""

        super().__init__()
        self.operation = operation

    def run(self) -> None:
        """在线程上下文中调用核心服务，并把结果转成 Qt 信号。"""

        try:
            result = self.operation()
        except Exception as exc:
            self.failed.emit(str(exc) or exc.__class__.__name__)
            return
        self.succeeded.emit(result)
