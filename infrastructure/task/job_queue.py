"""基于内存的任务队列占位实现。

这个文件给当前骨架提供了最小可用的队列抽象。
它属于 infrastructure 层，因为“队列如何保存”是执行细节，不是业务规则。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass(slots=True)
class JobQueue:
    """按进入顺序保存待处理任务。

    标准库里的 deque 很适合做两端追加和弹出操作。
    在真正的持久化队列引入前，它是一个足够简单、也适合教学阅读的占位结构。
    """

    _queue: deque = field(default_factory=deque)

    def enqueue(self, job) -> None:
        """把一个任务对象追加到队列尾部。"""

        self._queue.append(job)

    def size(self) -> int:
        """返回当前队列中的任务数量。"""

        return len(self._queue)
