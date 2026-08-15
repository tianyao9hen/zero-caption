"""线程安全的任务进度事件队列。

基础设施层把用例发布的任务快照放入标准库队列，
UI 线程再用 `QTimer` 定期取出快照并更新控件。
这样后台线程不会直接操作 Qt 控件，也不会跨线程调用界面对象。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from queue import Empty, Queue

from core.domain.entities import Task
from core.dto.subtitle_dto import TranslationProgressDTO
from core.dto.task_dto import TaskSummaryDTO


ProgressEvent = TaskSummaryDTO | TranslationProgressDTO


@dataclass(slots=True)
class ProgressBus:
    """保存待由界面消费的任务摘要和逐句翻译事件。"""

    _queue: Queue[ProgressEvent] = field(default_factory=Queue)

    def publish(self, task: Task) -> None:
        """把任务实体转换成轻量摘要并放入线程安全队列。"""

        self._queue.put(
            TaskSummaryDTO(
                task_id=task.task_id,
                task_type=task.task_type,
                status=task.status.value,
                progress=task.progress,
                current_step=task.current_step,
                message=task.message,
            )
        )

    def publish_translation(self, progress: TranslationProgressDTO) -> None:
        """把一条已完成的译文放入队列，等待 UI 线程展示。"""

        self._queue.put(progress)

    def drain(self) -> list[ProgressEvent]:
        """一次性取出当前积累的所有进度事件，不阻塞 UI 线程。"""

        events: list[ProgressEvent] = []
        while True:
            try:
                events.append(self._queue.get_nowait())
            except Empty:
                return events
