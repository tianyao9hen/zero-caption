"""核心领域实体模块。

实体表示系统里最重要的业务对象。它们属于 core 层，
应该尽量避免掺入 UI 和基础设施细节。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .enums import ProjectStatus, TaskCheckpoint, TaskStatus


def _now() -> datetime:
    """返回带时区信息的当前时间。

    这里集中封装时间获取，是为了让实体更新时间的逻辑保持一致，
    也方便未来测试或注入时间源时统一替换。
    """

    return datetime.now(UTC)


@dataclass(slots=True)
class Project:
    """表示应用正在跟踪的一个视频项目。

    这个实体只保存项目的稳定业务信息，例如源文件、语言设置、
    工作区目录和最近一次错误摘要。它不直接负责文件复制、
    队列调度或数据库写入，这些都属于其他层。
    """

    project_id: str
    source_video: Path
    source_language: str
    target_language: str
    workspace_dir: Path
    status: ProjectStatus = ProjectStatus.NEW
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    last_error: str = ""

    def mark_imported(self) -> None:
        """把项目标记为已导入状态。"""

        self.status = ProjectStatus.IMPORTED
        self.last_error = ""
        self.touch()

    def mark_processing(self) -> None:
        """把项目标记为处理中。"""

        self.status = ProjectStatus.PROCESSING
        self.last_error = ""
        self.touch()

    def mark_completed(self) -> None:
        """把项目标记为已完成。"""

        self.status = ProjectStatus.COMPLETED
        self.last_error = ""
        self.touch()

    def mark_failed(self, error_message: str) -> None:
        """把项目标记为失败，并记录最后一次错误。"""

        self.status = ProjectStatus.FAILED
        self.last_error = error_message
        self.touch()

    def touch(self) -> None:
        """刷新项目更新时间。"""

        self.updated_at = _now()


@dataclass(slots=True)
class Task:
    """表示一个和项目关联的工作单元。

    `Task` 负责表达“当前正在做什么、做到哪一步了、是否失败、能从哪里恢复”。
    真正的后台执行器以后会在基础设施层实现，但状态推进规则先在这里稳定下来。
    """

    task_id: str
    project_id: str
    task_type: str
    status: TaskStatus = TaskStatus.PENDING
    progress: int = 0
    checkpoint: TaskCheckpoint | None = None
    current_step: str = ""
    retry_count: int = 0
    message: str = ""
    error_message: str = ""
    created_at: datetime = field(default_factory=_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None

    def start(self, message: str = "") -> None:
        """把任务标记为开始执行。"""

        self.status = TaskStatus.RUNNING
        self.started_at = self.started_at or _now()
        self.finished_at = None
        self.error_message = ""
        if message:
            self.message = message

    def update_progress(
        self,
        progress: int,
        current_step: str,
        checkpoint: TaskCheckpoint | None,
        message: str,
    ) -> None:
        """更新任务进度和步骤信息。

        参数：
            progress：0 到 100 的整数进度。
            current_step：给用户展示的当前步骤短语。
            checkpoint：如果某个稳定步骤已经完成，就记录在这里。
            message：当前任务摘要。
        """

        if not 0 <= progress <= 100:
            raise ValueError("任务进度必须在 0 到 100 之间。")

        if checkpoint is not None:
            self._ensure_checkpoint_monotonic(checkpoint)
            self.checkpoint = checkpoint

        if self.status is TaskStatus.PENDING:
            self.start(message)
        else:
            self.status = TaskStatus.RUNNING

        self.progress = progress
        self.current_step = current_step
        self.message = message
        self.error_message = ""

    def mark_succeeded(
        self,
        message: str,
        checkpoint: TaskCheckpoint | None = None,
    ) -> None:
        """把任务标记为成功结束。"""

        if checkpoint is not None:
            self._ensure_checkpoint_monotonic(checkpoint)
            self.checkpoint = checkpoint

        self.status = TaskStatus.SUCCEEDED
        self.progress = 100
        self.message = message
        self.error_message = ""
        self.finished_at = _now()
        if self.started_at is None:
            self.started_at = self.created_at

    def mark_failed(self, error_message: str) -> None:
        """把任务标记为失败结束。"""

        self.status = TaskStatus.FAILED
        self.error_message = error_message
        self.message = error_message
        self.finished_at = _now()
        if self.started_at is None:
            self.started_at = self.created_at

    def increment_retry(self) -> None:
        """增加任务重试次数。"""

        self.retry_count += 1

    def _ensure_checkpoint_monotonic(self, next_checkpoint: TaskCheckpoint) -> None:
        """确保检查点只能前进不能后退。"""

        if self.checkpoint is None:
            return

        ordered = list(TaskCheckpoint)
        if ordered.index(next_checkpoint) < ordered.index(self.checkpoint):
            raise ValueError("任务检查点不允许回退。")
