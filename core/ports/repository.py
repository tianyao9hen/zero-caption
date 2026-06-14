"""仓储抽象端口定义模块。"""

from __future__ import annotations

from typing import Protocol


class TaskRepository(Protocol):
    """任务记录持久化所需的能力。"""

    def save(self, task): ...
