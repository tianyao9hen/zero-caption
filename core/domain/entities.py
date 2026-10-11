"""核心领域实体模块。

实体表示系统里最重要的业务对象。它们属于 core 层，
应该尽量避免掺入 UI 和基础设施细节。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .enums import (
    ExportMode,
    ProcessingMode,
    ProjectStatus,
    TaskCheckpoint,
    TaskStatus,
)


def _now() -> datetime:
    """返回带时区信息的当前时间。

    这里集中封装时间获取，是为了让实体更新时间的逻辑保持一致，
    也方便未来测试或注入时间源时统一替换。
    """

    return datetime.now(UTC)


@dataclass(slots=True)
class Project:
    """表示应用正在跟踪的一个视频项目。

    这个实体保存项目的稳定业务信息，例如源文件、语言设置、处理模式、
    翻译上下文、导出参数和最近一次错误摘要。持久化这些请求参数后，
    应用重启才能继续原项目。烧录任务还会在这里记录项目目录内已预生成的
    成品路径与对应字幕指纹。实体本身不负责文件复制、队列调度或数据库
    写入，这些都属于其他层。
    """

    project_id: str
    source_video: Path
    source_language: str
    target_language: str
    workspace_dir: Path
    source_fingerprint: str = ""
    translation_context: str = ""
    processing_mode: ProcessingMode = ProcessingMode.FULL_PIPELINE
    export_mode: ExportMode = ExportMode.SOFT_SUBTITLE
    # 这里保存用户可见的最近成果路径：仅识别任务和外挂字幕下载是 `.srt`，
    # 烧录模式才记录视频成品。内部字幕和缓存固定放在项目工作区。
    output_path: Path | None = None
    # 选择烧录字幕的任务会在翻译完成后自动在项目自己的 `exports/` 目录里
    # 预生成一份成品视频。用户点击“下载成品”时只需要复制这份文件，
    # 不必每次下载都重新编码几十分钟。这里记录的就是那份内部成品路径。
    prepared_output_path: Path | None = None
    # 生成内部成品时使用的译文字幕指纹。用户手工修订某条译文后，指纹会跟着
    # 变化，程序据此判断内部成品是否已经过期，避免把旧译文的硬字幕交付出去。
    prepared_translation_signature: str = ""
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
        current_step: str = "已完成",
    ) -> None:
        """把任务标记为成功结束。

        参数：
            message：给用户展示的成功摘要，例如“下载完成：xxx.mp4”。
            checkpoint：任务成功后稳定停留的检查点，可为空。
            current_step：成功瞬间的“当前步骤”文案。这里必须允许调用方
                覆盖，因为运行期写入的 `current_step` 往往是“正在生成成品
                99%”这类进行时描述如果不覆盖，会在任务完成后继续显示，
                让用户误以为任务仍卡在最后一步。

        说明：
            运行期进度文案描述的是“此刻在做什么”，成功之后这个语义就不成立
            了。因此成功收口时必须换成完成态文案，而不是保留最后一条进度。
        """

        if checkpoint is not None:
            self._ensure_checkpoint_monotonic(checkpoint)
            self.checkpoint = checkpoint

        self.status = TaskStatus.SUCCEEDED
        self.progress = 100
        self.message = message
        self.current_step = current_step
        self.error_message = ""
        self.finished_at = _now()
        if self.started_at is None:
            self.started_at = self.created_at

    def mark_failed(self, error_message: str, current_step: str = "执行失败") -> None:
        """把任务标记为失败结束。

        参数：
            error_message：失败原因，会同时写入消息和错误字段。
            current_step：失败瞬间的“当前步骤”文案。同样需要覆盖运行期
                进度文案，否则界面会停在“正在生成成品 99%”这种看似还在
                正常运行的假象上，掩盖真正的失败。

        说明：
            失败和成功一样都属于终态，必须同步收口 `current_step`。
        """

        self.status = TaskStatus.FAILED
        self.error_message = error_message
        self.message = error_message
        self.current_step = current_step
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
