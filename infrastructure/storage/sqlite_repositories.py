"""SQLite 仓储实现。

仓储把领域实体和 DTO 转成可持久化的标量字段，再从数据库还原对象。
它们不编排识别、翻译或导出顺序，因此核心用例可以继续使用同一组端口。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core.domain.entities import Project, Task
from core.domain.enums import (
    ExportMode,
    ProcessingMode,
    ProjectStatus,
    TaskCheckpoint,
    TaskStatus,
)
from core.dto.subtitle_dto import SubtitleSegmentDTO
from core.dto.task_dto import ExportRecordDTO
from infrastructure.storage.sqlite_db import SQLiteDatabase


def _encode_time(value: datetime | None) -> str | None:
    """把带时区时间编码成 SQLite 可保存的 ISO 字符串。"""

    return value.isoformat() if value is not None else None


def _decode_time(value: str | None) -> datetime | None:
    """把数据库中的 ISO 字符串还原成时间对象。"""

    return datetime.fromisoformat(value) if value else None


@dataclass(slots=True)
class SQLiteProjectRepository:
    """持久化 `Project` 实体，并支持启动时读取历史项目。"""

    database: SQLiteDatabase

    def save(self, project: Project) -> Project:
        """插入或更新项目记录。"""

        with self.database.connection() as connection:
            connection.execute(
                """
                INSERT INTO projects (
                    project_id, source_video, source_language, target_language,
                    workspace_dir, source_fingerprint, translation_context,
                    processing_mode, export_mode, output_path, status, created_at,
                    updated_at, last_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    source_video=excluded.source_video,
                    source_language=excluded.source_language,
                    target_language=excluded.target_language,
                    workspace_dir=excluded.workspace_dir,
                    source_fingerprint=excluded.source_fingerprint,
                    translation_context=excluded.translation_context,
                    processing_mode=excluded.processing_mode,
                    export_mode=excluded.export_mode,
                    output_path=excluded.output_path,
                    status=excluded.status,
                    updated_at=excluded.updated_at,
                    last_error=excluded.last_error
                """,
                (
                    project.project_id,
                    str(project.source_video),
                    project.source_language,
                    project.target_language,
                    str(project.workspace_dir),
                    project.source_fingerprint,
                    project.translation_context,
                    project.processing_mode.value,
                    project.export_mode.value,
                    str(project.output_path) if project.output_path else None,
                    project.status.value,
                    _encode_time(project.created_at),
                    _encode_time(project.updated_at),
                    project.last_error,
                ),
            )
        return project

    def get_by_id(self, project_id: str) -> Project | None:
        """按项目编号读取实体，不存在时返回 `None`。"""

        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM projects WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        return self._from_row(row) if row else None

    def list_all(self) -> list[Project]:
        """按更新时间倒序返回历史项目。"""

        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM projects ORDER BY updated_at DESC"
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def delete(self, project_id: str) -> bool:
        """在一个事务中删除项目及其任务、字幕和导出记录。

        删除顺序先从属表、后项目表，兼容早期数据库中没有配置
        `ON DELETE CASCADE` 的外键定义。事务可以防止任务列表已经消失、
        字幕记录却仍残留的半删除状态。
        """

        with self.database.connection() as connection:
            connection.execute(
                "DELETE FROM export_records WHERE project_id = ?",
                (project_id,),
            )
            connection.execute(
                "DELETE FROM subtitle_segments WHERE project_id = ?",
                (project_id,),
            )
            connection.execute(
                "DELETE FROM tasks WHERE project_id = ?",
                (project_id,),
            )
            cursor = connection.execute(
                "DELETE FROM projects WHERE project_id = ?",
                (project_id,),
            )
        return cursor.rowcount > 0

    @staticmethod
    def _from_row(row) -> Project:
        """把一行数据库记录还原为领域项目实体。"""

        return Project(
            project_id=row["project_id"],
            source_video=Path(row["source_video"]),
            source_language=row["source_language"],
            target_language=row["target_language"],
            workspace_dir=Path(row["workspace_dir"]),
            source_fingerprint=row["source_fingerprint"],
            translation_context=row["translation_context"],
            processing_mode=ProcessingMode(row["processing_mode"]),
            export_mode=ExportMode(row["export_mode"]),
            output_path=Path(row["output_path"]) if row["output_path"] else None,
            status=ProjectStatus(row["status"]),
            created_at=_decode_time(row["created_at"]),
            updated_at=_decode_time(row["updated_at"]),
            last_error=row["last_error"],
        )


@dataclass(slots=True)
class SQLiteTaskRepository:
    """持久化任务状态，并提供重启恢复所需的查询。"""

    database: SQLiteDatabase

    def save(self, task: Task) -> Task:
        """插入或更新任务快照。"""

        with self.database.connection() as connection:
            connection.execute(
                """
                INSERT INTO tasks (
                    task_id, project_id, task_type, status, progress, checkpoint,
                    current_step, retry_count, message, error_message, created_at,
                    started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    status=excluded.status,
                    progress=excluded.progress,
                    checkpoint=excluded.checkpoint,
                    current_step=excluded.current_step,
                    retry_count=excluded.retry_count,
                    message=excluded.message,
                    error_message=excluded.error_message,
                    started_at=excluded.started_at,
                    finished_at=excluded.finished_at
                """,
                (
                    task.task_id,
                    task.project_id,
                    task.task_type,
                    task.status.value,
                    task.progress,
                    task.checkpoint.value if task.checkpoint else None,
                    task.current_step,
                    task.retry_count,
                    task.message,
                    task.error_message,
                    _encode_time(task.created_at),
                    _encode_time(task.started_at),
                    _encode_time(task.finished_at),
                ),
            )
        return task

    def get_by_id(self, task_id: str) -> Task | None:
        """按任务编号读取任务实体。"""

        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        return self._from_row(row) if row else None

    def list_by_project(self, project_id: str) -> list[Task]:
        """读取项目的任务历史，最新任务排在前面。"""

        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM tasks WHERE project_id = ? ORDER BY created_at DESC",
                (project_id,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def list_incomplete(self) -> list[Task]:
        """读取尚未成功或失败结束的任务。"""

        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM tasks WHERE status IN (?, ?) ORDER BY created_at",
                (TaskStatus.PENDING.value, TaskStatus.RUNNING.value),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def recover_running_tasks(self) -> list[Task]:
        """把进程异常退出留下的运行中任务改回可重试的待处理状态。"""

        with self.database.connection() as connection:
            connection.execute(
                """
                UPDATE tasks
                SET status = ?, message = ?, error_message = ?, finished_at = NULL
                WHERE status = ?
                """,
                (
                    TaskStatus.PENDING.value,
                    "应用重启后等待恢复",
                    "",
                    TaskStatus.RUNNING.value,
                ),
            )
        return self.list_incomplete()

    @staticmethod
    def _from_row(row) -> Task:
        """把一行数据库记录还原为任务实体。"""

        checkpoint = row["checkpoint"]
        return Task(
            task_id=row["task_id"],
            project_id=row["project_id"],
            task_type=row["task_type"],
            status=TaskStatus(row["status"]),
            progress=int(row["progress"]),
            checkpoint=TaskCheckpoint(checkpoint) if checkpoint else None,
            current_step=row["current_step"],
            retry_count=int(row["retry_count"]),
            message=row["message"],
            error_message=row["error_message"],
            created_at=_decode_time(row["created_at"]),
            started_at=_decode_time(row["started_at"]),
            finished_at=_decode_time(row["finished_at"]),
        )


@dataclass(slots=True)
class SQLiteSubtitleRepository:
    """持久化原文和译文字幕片段。"""

    database: SQLiteDatabase

    def save_source_segments(self, project_id: str, segments: list[SubtitleSegmentDTO]) -> list[SubtitleSegmentDTO]:
        """替换项目的原文字幕片段并返回副本。"""

        return self._save_segments(project_id, "source", "", segments)

    def get_source_segments(self, project_id: str) -> list[SubtitleSegmentDTO]:
        """读取项目的原文字幕片段。"""

        return self._get_segments(project_id, "source", "")

    def save_translated_segments(self, project_id: str, target_language: str, segments: list[SubtitleSegmentDTO]) -> list[SubtitleSegmentDTO]:
        """替换项目指定语言的译文字幕片段。"""

        return self._save_segments(project_id, "translated", target_language, segments)

    def get_translated_segments(self, project_id: str, target_language: str) -> list[SubtitleSegmentDTO]:
        """读取项目指定语言的译文字幕片段。"""

        return self._get_segments(project_id, "translated", target_language)

    def _save_segments(self, project_id: str, version: str, target_language: str, segments: list[SubtitleSegmentDTO]) -> list[SubtitleSegmentDTO]:
        """在事务中删除旧版本并写入新片段。"""

        with self.database.connection() as connection:
            connection.execute(
                "DELETE FROM subtitle_segments WHERE project_id = ? AND version = ? AND target_language = ?",
                (project_id, version, target_language),
            )
            connection.executemany(
                """
                INSERT INTO subtitle_segments (
                    project_id, version, target_language, segment_id, ordinal,
                    start_ms, end_ms, text, language
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        project_id,
                        version,
                        target_language,
                        segment.segment_id,
                        ordinal,
                        segment.start_ms,
                        segment.end_ms,
                        segment.text,
                        segment.language,
                    )
                    for ordinal, segment in enumerate(segments)
                ],
            )
        return list(segments)

    def _get_segments(self, project_id: str, version: str, target_language: str) -> list[SubtitleSegmentDTO]:
        """按原有顺序读取字幕片段。"""

        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT segment_id, start_ms, end_ms, text, language
                FROM subtitle_segments
                WHERE project_id = ? AND version = ? AND target_language = ?
                ORDER BY ordinal
                """,
                (project_id, version, target_language),
            ).fetchall()
        return [
            SubtitleSegmentDTO(
                segment_id=row["segment_id"],
                start_ms=int(row["start_ms"]),
                end_ms=int(row["end_ms"]),
                text=row["text"],
                language=row["language"],
            )
            for row in rows
        ]


@dataclass(slots=True)
class SQLiteExportRecordRepository:
    """持久化导出记录并读取项目最近一次导出。"""

    database: SQLiteDatabase

    def save(self, record: ExportRecordDTO) -> ExportRecordDTO:
        """新增导出记录。"""

        from datetime import datetime, UTC

        with self.database.connection() as connection:
            connection.execute(
                """
                INSERT INTO export_records (
                    project_id, source_video, subtitle_path, output_path, mode, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    record.project_id,
                    str(record.source_video),
                    str(record.subtitle_path),
                    str(record.output_path),
                    record.mode.value,
                    datetime.now(UTC).isoformat(),
                ),
            )
        return record

    def get_latest_by_project(self, project_id: str) -> ExportRecordDTO | None:
        """读取项目最近一次导出记录。"""

        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM export_records WHERE project_id = ? ORDER BY export_id DESC LIMIT 1",
                (project_id,),
            ).fetchone()
        if row is None:
            return None
        from core.domain.enums import ExportMode

        return ExportRecordDTO(
            project_id=row["project_id"],
            source_video=Path(row["source_video"]),
            subtitle_path=Path(row["subtitle_path"]),
            output_path=Path(row["output_path"]),
            mode=ExportMode(row["mode"]),
        )
