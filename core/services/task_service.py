"""面向任务的应用服务模块。

这个服务紧贴 core 层。UI 应该通过这种服务获取任务状态，而不是直接操作队列。
当前骨架里的行为还很少，但它已经标出了未来任务创建、进度更新和状态查询的入口位置。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging

from infrastructure.task.job_queue import JobQueue


@dataclass(slots=True)
class TaskService:
    """为任务相关状态提供一个简单的访问接口。"""

    job_queue: JobQueue
    logger: logging.Logger
    _latest_message: str = field(default="No active task", init=False)

    def summary(self) -> str:
        """返回一段给 UI 展示的简短任务摘要。

        状态栏和任务页都会调用这个方法。当前先返回普通字符串，
        这样在完整任务系统尚未实现前，第一版界面仍然容易展示和调试。
        """

        return self._latest_message
