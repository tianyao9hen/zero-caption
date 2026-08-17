"""开发阶段使用的内存仓储实现。

这些仓储让阶段 2 和阶段 3 可以先打通无界面主链路，
但它们不是最终真实状态来源。阶段 5 会用 SQLite 实现替换它们，
核心用例不需要因此改动接口。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.domain.entities import Project, Task
from core.dto.subtitle_dto import SubtitleSegmentDTO
from core.dto.task_dto import ExportRecordDTO


@dataclass(slots=True)
class InMemoryProjectRepository:
    """在进程内保存项目实体的临时仓储。"""

    _items: dict[str, Project] = field(default_factory=dict)

    def save(self, project: Project) -> Project:
        """保存项目实体并返回同一个对象。"""

        self._items[project.project_id] = project
        return project

    def get_by_id(self, project_id: str) -> Project | None:
        """按项目编号读取实体，不存在时返回 `None`。"""

        return self._items.get(project_id)

    def list_all(self) -> list[Project]:
        """按最近更新时间返回全部项目，行为与 SQLite 仓储保持一致。"""

        return sorted(
            self._items.values(),
            key=lambda project: project.updated_at,
            reverse=True,
        )

    def delete(self, project_id: str) -> bool:
        """删除指定项目，供核心服务和轻量测试使用。"""

        return self._items.pop(project_id, None) is not None


@dataclass(slots=True)
class InMemoryTaskRepository:
    """在进程内保存任务实体的临时仓储。"""

    _items: dict[str, Task] = field(default_factory=dict)

    def save(self, task: Task) -> Task:
        """保存任务实体并返回同一个对象。"""

        self._items[task.task_id] = task
        return task

    def get_by_id(self, task_id: str) -> Task | None:
        """按任务编号读取实体，不存在时返回 `None`。"""

        return self._items.get(task_id)

    def list_by_project(self, project_id: str) -> list[Task]:
        """返回一个项目的内部任务，最新创建的任务排在前面。"""

        return sorted(
            (
                task
                for task in self._items.values()
                if task.project_id == project_id
            ),
            key=lambda task: task.created_at,
            reverse=True,
        )


@dataclass(slots=True)
class InMemorySubtitleRepository:
    """在进程内保存原文和译文字幕片段。"""

    _source_items: dict[str, list[SubtitleSegmentDTO]] = field(default_factory=dict)
    _translated_items: dict[tuple[str, str], list[SubtitleSegmentDTO]] = field(
        default_factory=dict
    )

    def save_source_segments(
        self,
        project_id: str,
        segments: list[SubtitleSegmentDTO],
    ) -> list[SubtitleSegmentDTO]:
        """保存原文字幕片段，并返回列表副本。"""

        self._source_items[project_id] = list(segments)
        return list(segments)

    def get_source_segments(self, project_id: str) -> list[SubtitleSegmentDTO]:
        """读取原文字幕片段，并返回列表副本。"""

        return list(self._source_items.get(project_id, []))

    def save_translated_segments(
        self,
        project_id: str,
        target_language: str,
        segments: list[SubtitleSegmentDTO],
    ) -> list[SubtitleSegmentDTO]:
        """按项目和目标语言保存译文字幕片段。"""

        key = (project_id, target_language)
        self._translated_items[key] = list(segments)
        return list(segments)

    def get_translated_segments(
        self,
        project_id: str,
        target_language: str,
    ) -> list[SubtitleSegmentDTO]:
        """读取指定语言的译文字幕片段。"""

        return list(self._translated_items.get((project_id, target_language), []))


@dataclass(slots=True)
class InMemoryExportRecordRepository:
    """在进程内保存导出记录的临时仓储。"""

    _items: list[ExportRecordDTO] = field(default_factory=list)

    def save(self, record: ExportRecordDTO) -> ExportRecordDTO:
        """追加导出记录并返回同一个 DTO。"""

        self._items.append(record)
        return record

    def get_latest_by_project(self, project_id: str) -> ExportRecordDTO | None:
        """读取项目最近一次导出记录。"""

        for record in reversed(self._items):
            if record.project_id == project_id:
                return record
        return None
