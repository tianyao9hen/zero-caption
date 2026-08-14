"""持久化任务的最小 worker 实现。

worker 只负责领取队列记录、调用外部处理函数并回写结果，
不包含视频识别或翻译规则。这样未来可以把 `TaskService` 作为 handler 注入，
也可以在不改变队列状态机的情况下替换线程或进程执行器。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from infrastructure.task.job_queue import PersistentJob, PersistentJobQueue


@dataclass(slots=True)
class TaskWorker:
    """一次只处理一条队列任务的 worker。"""

    queue: PersistentJobQueue

    def run_once(self, handler: Callable[[PersistentJob], None]) -> bool:
        """领取并处理一条任务；没有任务时返回 `False`。"""

        job = self.queue.claim_next()
        if job is None:
            return False
        try:
            handler(job)
        except Exception as exc:
            self.queue.mark_failed(job.job_id, str(exc) or exc.__class__.__name__)
            return True
        self.queue.mark_succeeded(job.job_id)
        return True
