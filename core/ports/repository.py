"""仓储抽象端口定义模块。"""

from __future__ import annotations

from typing import Protocol

from core.domain.entities import Project, Task
from core.dto.subtitle_dto import SubtitleSegmentDTO
from core.dto.task_dto import ExportRecordDTO


class ProjectRepository(Protocol):
    """项目记录持久化所需的最小能力。"""

    def save(self, project: Project) -> Project: ...

    def get_by_id(self, project_id: str) -> Project | None: ...


class TaskRepository(Protocol):
    """任务记录持久化所需的最小能力。"""

    def save(self, task: Task) -> Task: ...

    def get_by_id(self, task_id: str) -> Task | None: ...


class SubtitleRepository(Protocol):
    """字幕片段读写所需的最小能力。"""

    def save_source_segments(
        self,
        project_id: str,
        segments: list[SubtitleSegmentDTO],
    ) -> list[SubtitleSegmentDTO]: ...

    def get_source_segments(self, project_id: str) -> list[SubtitleSegmentDTO]: ...

    def save_translated_segments(
        self,
        project_id: str,
        target_language: str,
        segments: list[SubtitleSegmentDTO],
    ) -> list[SubtitleSegmentDTO]: ...

    def get_translated_segments(
        self,
        project_id: str,
        target_language: str,
    ) -> list[SubtitleSegmentDTO]: ...


class ExportRecordRepository(Protocol):
    """导出记录读写所需的最小能力。"""

    def save(self, record: ExportRecordDTO) -> ExportRecordDTO: ...

    def get_latest_by_project(self, project_id: str) -> ExportRecordDTO | None: ...
