"""任务事件发布端口定义模块。

这个端口属于 `core/ports`，用于描述核心层如何把任务状态变化发布给外部。
阶段 1 只定接口，不绑定 Qt 信号、消息总线或数据库通知。
"""

from __future__ import annotations

from typing import Protocol

from core.domain.entities import Task
from core.dto.subtitle_dto import TranslationProgressDTO


class TaskEventPublisher(Protocol):
    """发布任务状态快照的最小能力。"""

    def publish(self, task: Task) -> None: ...


class TranslationProgressPublisher(Protocol):
    """发布逐句翻译结果，供界面层实时追加展示。"""

    def publish_translation(self, progress: TranslationProgressDTO) -> None: ...
