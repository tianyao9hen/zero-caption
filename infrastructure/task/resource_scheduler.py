"""进程内高资源任务调度器。

这个模块属于基础设施层，使用标准库信号量限制高资源操作的并发数。
它不判断业务步骤是否昂贵；哪些操作需要受限由核心服务明确决定。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from threading import BoundedSemaphore
from typing import TypeVar


ResultT = TypeVar("ResultT")


@dataclass(slots=True)
class SerialResourceScheduler:
    """让多个后台任务共享有限数量的高资源执行槽位。

    `BoundedSemaphore` 是线程安全的计数信号量。默认只有一个槽位，
    因而识别、视频导出等步骤会排队串行执行；任务的翻译等轻量阶段
    不经过这里，仍然可以和其他视频任务并行推进。
    """

    max_concurrency: int = 1
    _semaphore: BoundedSemaphore = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """校验并创建进程内共享信号量，不访问文件或外部系统。"""

        if self.max_concurrency <= 0:
            raise ValueError("高资源任务并发数必须大于 0。")
        self._semaphore = BoundedSemaphore(self.max_concurrency)

    def run(
        self,
        operation_name: str,
        operation: Callable[[], ResultT],
    ) -> ResultT:
        """等待一个资源槽位并执行操作，结束后一定归还槽位。

        参数：
            operation_name：调用方提供的诊断名称；当前实现无需按名称分组。
            operation：需要受并发保护的同步函数。

        返回：
            原函数返回值。

        副作用：
            可能阻塞当前后台线程等待槽位，但不会阻塞 Qt 界面线程。
        """

        # `with` 会在函数正常返回或抛出异常时都释放信号量，避免某次失败
        # 永久占住资源槽位。变量保留名称是为了让调试器中能看到操作类别。
        _ = operation_name
        with self._semaphore:
            return operation()
