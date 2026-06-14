"""应用内共享的稳定领域枚举。

枚举可以替代散落各处的魔法字符串，用受控的可选值集合表达状态，
这样状态流转更容易阅读，也更不容易写错。
"""

from __future__ import annotations

from enum import Enum


class ProjectStatus(str, Enum):
    """字幕项目的生命周期状态。"""

    NEW = "new"
    IMPORTED = "imported"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskStatus(str, Enum):
    """后台任务的执行状态。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ExportMode(str, Enum):
    """字幕导出的支持模式。"""

    SOFT_SUBTITLE = "soft_subtitle"
    BURN_IN = "burn_in"
