"""高资源任务调度端口。

这个端口位于核心层，用来表达识别、视频导出等步骤需要受资源并发限制。
核心服务只声明哪些操作属于高资源阶段，不依赖线程锁或信号量的具体实现。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, TypeVar


ResultT = TypeVar("ResultT")


class ResourceScheduler(Protocol):
    """定义在受控资源槽位中执行一个同步操作的能力。"""

    def run(
        self,
        operation_name: str,
        operation: Callable[[], ResultT],
    ) -> ResultT:
        """等待资源槽位、执行操作并返回原操作结果。

        参数：
            operation_name：用于日志和诊断的稳定操作名称。
            operation：拿到资源槽位后执行的无参数同步函数。

        返回：
            原操作的返回值。实现不得吞掉原操作抛出的异常。
        """

        ...
