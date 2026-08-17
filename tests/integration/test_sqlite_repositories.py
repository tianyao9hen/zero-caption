"""SQLite 仓储集成测试，保护应用重启后的数据可见性和状态恢复。"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
import sqlite3

from core.domain.entities import Project, Task
from core.domain.enums import (
    ExportMode,
    ProcessingMode,
    ProjectStatus,
    TaskCheckpoint,
    TaskStatus,
)
from core.dto.subtitle_dto import (
    EditSubtitleTranslationInput,
    SubtitleSegmentDTO,
)
from core.dto.task_dto import ExportRecordDTO
from core.services.task_service import TaskService
from core.usecases.revise_subtitle_translation import ReviseSubtitleTranslation
from infrastructure.storage.sqlite_db import SQLiteDatabase
from infrastructure.storage.sqlite_repositories import (
    SQLiteExportRecordRepository,
    SQLiteProjectRepository,
    SQLiteSubtitleRepository,
    SQLiteTaskRepository,
)
from infrastructure.subtitle.srt_writer import SrtWriter


def test_sqlite_repositories_round_trip_domain_data(tmp_path) -> None:
    """项目、任务、字幕和导出记录写入后，新的仓储实例仍能读取。"""

    # arrange：使用临时数据库模拟应用关闭后再次启动。
    database = SQLiteDatabase(tmp_path / "zero-caption.sqlite3")
    projects = SQLiteProjectRepository(database)
    tasks = SQLiteTaskRepository(database)
    subtitles = SQLiteSubtitleRepository(database)
    exports = SQLiteExportRecordRepository(database)
    project = Project(
        project_id="project-1",
        source_video=tmp_path / "source.mp4",
        source_language="en",
        target_language="zh-CN",
        workspace_dir=tmp_path / "projects" / "project-1",
        translation_context="课程术语：agent 译为智能体",
        processing_mode=ProcessingMode.FULL_PIPELINE,
        export_mode=ExportMode.BURN_IN,
        output_path=tmp_path / "exports" / "lesson.mp4",
    )
    project.mark_imported()
    task = Task(task_id="task-1", project_id=project.project_id, task_type="demo")
    task.update_progress(40, "识别", TaskCheckpoint.AUDIO_EXTRACTED, "已抽取")
    segments = [SubtitleSegmentDTO("s1", 0, 1000, "hello", "en")]
    record = ExportRecordDTO(
        project_id=project.project_id,
        source_video=project.source_video,
        subtitle_path=tmp_path / "translated.srt",
        output_path=tmp_path / "output.mp4",
        mode=ExportMode.SOFT_SUBTITLE,
    )

    # act：保存所有结构化记录。
    projects.save(project)
    tasks.save(task)
    subtitles.save_source_segments(project.project_id, segments)
    subtitles.save_translated_segments(project.project_id, "zh-CN", [
        SubtitleSegmentDTO("s1", 0, 1000, "你好", "zh-CN")
    ])
    exports.save(record)

    # assert：重新创建仓储对象，验证数据来自磁盘而不是旧内存对象。
    reopened = SQLiteDatabase(tmp_path / "zero-caption.sqlite3")
    restored_project = SQLiteProjectRepository(reopened).get_by_id("project-1")
    restored_task = SQLiteTaskRepository(reopened).get_by_id("task-1")
    restored_source = SQLiteSubtitleRepository(reopened).get_source_segments("project-1")
    restored_translation = SQLiteSubtitleRepository(reopened).get_translated_segments(
        "project-1", "zh-CN"
    )
    restored_export = SQLiteExportRecordRepository(reopened).get_latest_by_project("project-1")

    assert restored_project is not None
    assert restored_project.status is ProjectStatus.IMPORTED
    assert restored_project.source_video == project.source_video
    assert restored_project.translation_context == project.translation_context
    assert restored_project.processing_mode is ProcessingMode.FULL_PIPELINE
    assert restored_project.export_mode is ExportMode.BURN_IN
    assert restored_project.output_path == project.output_path
    assert restored_task is not None
    assert restored_task.checkpoint is TaskCheckpoint.AUDIO_EXTRACTED
    assert restored_task.progress == 40
    assert restored_source == segments
    assert restored_translation[0].text == "你好"
    assert restored_export is not None
    assert restored_export.mode is ExportMode.SOFT_SUBTITLE


def test_sqlite_project_delete_removes_all_dependent_records(tmp_path) -> None:
    """删除项目时应在一个事务中同步移除任务、字幕和导出历史。"""

    database = SQLiteDatabase(tmp_path / "delete.sqlite3")
    projects = SQLiteProjectRepository(database)
    tasks = SQLiteTaskRepository(database)
    subtitles = SQLiteSubtitleRepository(database)
    exports = SQLiteExportRecordRepository(database)
    project = Project(
        project_id="project-delete",
        source_video=tmp_path / "source.mp4",
        source_language="en",
        target_language="zh-CN",
        workspace_dir=tmp_path / "projects" / "project-delete",
    )
    task = Task("task-delete", project.project_id, "translate_subtitles")
    segment = SubtitleSegmentDTO("segment-1", 0, 1_000, "hello", "en")
    record = ExportRecordDTO(
        project_id=project.project_id,
        source_video=project.source_video,
        subtitle_path=tmp_path / "translated.srt",
        output_path=tmp_path / "output.mp4",
        mode=ExportMode.SOFT_SUBTITLE,
    )
    projects.save(project)
    tasks.save(task)
    subtitles.save_source_segments(project.project_id, [segment])
    exports.save(record)

    deleted = projects.delete(project.project_id)

    assert deleted is True
    with database.connection() as connection:
        counts = {
            table: connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            for table in (
                "projects",
                "tasks",
                "subtitle_segments",
                "export_records",
            )
        }
    assert counts == {
        "projects": 0,
        "tasks": 0,
        "subtitle_segments": 0,
        "export_records": 0,
    }


def test_sqlite_database_migrates_legacy_project_request_columns(tmp_path) -> None:
    """旧版项目表应自动补充恢复请求列，不要求用户删除历史数据库。"""

    # arrange：直接创建升级前的项目表和一条历史记录，模拟用户已有数据。
    database_path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE projects (
                project_id TEXT PRIMARY KEY,
                source_video TEXT NOT NULL,
                source_language TEXT NOT NULL,
                target_language TEXT NOT NULL,
                workspace_dir TEXT NOT NULL,
                source_fingerprint TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_error TEXT NOT NULL DEFAULT ''
            );
            INSERT INTO projects (
                project_id, source_video, source_language, target_language,
                workspace_dir, status, created_at, updated_at
            ) VALUES (
                'legacy-project', 'legacy.mp4', 'en', 'zh-CN', 'legacy-workspace',
                'completed', '2026-08-16T08:00:00+00:00',
                '2026-08-16T08:00:00+00:00'
            );
            """
        )

    # act：常规初始化应在同一数据库上执行增量迁移。
    repository = SQLiteProjectRepository(SQLiteDatabase(database_path))
    restored = repository.get_by_id("legacy-project")

    # assert：历史记录仍在，并获得兼容旧版本的安全默认请求参数。
    assert restored is not None
    assert restored.translation_context == ""
    assert restored.processing_mode is ProcessingMode.FULL_PIPELINE
    assert restored.export_mode is ExportMode.SOFT_SUBTITLE
    assert restored.output_path is None


def test_sqlite_task_repository_recovers_running_tasks(tmp_path) -> None:
    """应用重启时，运行中的任务应回到待处理而不是永久卡住。"""

    database = SQLiteDatabase(tmp_path / "zero-caption.sqlite3")
    projects = SQLiteProjectRepository(database)
    tasks = SQLiteTaskRepository(database)
    project = Project(
        project_id="project-1",
        source_video=Path("source.mp4"),
        source_language="auto",
        target_language="zh-CN",
        workspace_dir=tmp_path,
    )
    projects.save(project)
    task = Task(task_id="task-1", project_id=project.project_id, task_type="demo")
    task.start("正在处理")
    tasks.save(task)

    # act：模拟新进程启动时执行恢复扫描。
    recovered = tasks.recover_running_tasks()

    # assert：任务仍保留原记录，但状态变为可重新领取的 pending。
    assert len(recovered) == 1
    assert recovered[0].status is TaskStatus.PENDING
    assert recovered[0].message == "应用重启后等待恢复"


def test_task_service_restores_one_video_history_item_after_restart(tmp_path) -> None:
    """重启后任务页查询应把同一项目的多个步骤聚合为一个视频条目。"""

    database_path = tmp_path / "zero-caption.sqlite3"
    database = SQLiteDatabase(database_path)
    projects = SQLiteProjectRepository(database)
    tasks = SQLiteTaskRepository(database)
    started_at = datetime(2026, 8, 16, 8, 0, tzinfo=UTC)
    project = Project(
        project_id="project-history",
        source_video=tmp_path / "history.mp4",
        source_language="auto",
        target_language="zh-CN",
        workspace_dir=tmp_path / "projects" / "project-history",
        created_at=started_at,
        updated_at=started_at,
    )
    project.mark_processing()
    projects.save(project)

    imported = Task(
        task_id="task-imported",
        project_id=project.project_id,
        task_type="create_project",
        created_at=started_at,
    )
    imported.mark_succeeded("项目已导入", TaskCheckpoint.IMPORTED)
    translating = Task(
        task_id="task-translating",
        project_id=project.project_id,
        task_type="translate_subtitles",
        created_at=started_at + timedelta(seconds=1),
    )
    translating.update_progress(
        70,
        "逐句翻译 3/5",
        TaskCheckpoint.TRANSCRIBED,
        "已翻译第 3 条字幕",
    )
    tasks.save(imported)
    tasks.save(translating)

    # act：重新创建数据库和仓储对象，模拟应用关闭后再次进入任务页。
    reopened = SQLiteDatabase(database_path)
    service = TaskService(
        project_repository=SQLiteProjectRepository(reopened),
        task_repository=SQLiteTaskRepository(reopened),
    )
    history = service.list_video_tasks()

    # assert：一个视频只占一行，并采用最近内部任务的状态。
    assert len(history) == 1
    assert history[0].project_id == project.project_id
    assert history[0].source_video.name == "history.mp4"
    assert history[0].task_id == translating.task_id
    assert history[0].progress == 70
    assert history[0].checkpoint == TaskCheckpoint.TRANSCRIBED.value


def test_edited_translation_survives_database_reopen_and_updates_srt(tmp_path) -> None:
    """手工修订应同时写入 SQLite 和正式字幕文件，重启后仍可读取。"""

    class UnusedTranslator:
        """手工编辑不应调用翻译端口；若误调用就让测试立即失败。"""

        def translate_segments(self, *args, **kwargs):
            """拒绝所有意外模型调用。"""

            raise AssertionError("手工编辑不应该调用大模型")

    # arrange：用真实 SQLite 仓储保存一个项目和两条完整字幕。
    database_path = tmp_path / "revision.sqlite3"
    database = SQLiteDatabase(database_path)
    projects = SQLiteProjectRepository(database)
    tasks = SQLiteTaskRepository(database)
    subtitles = SQLiteSubtitleRepository(database)
    project = Project(
        project_id="project-reopen-edit",
        source_video=tmp_path / "lesson.mp4",
        source_language="en",
        target_language="zh-CN",
        workspace_dir=tmp_path / "project-reopen-edit",
    )
    project.mark_completed()
    projects.save(project)
    subtitles.save_source_segments(
        project.project_id,
        [SubtitleSegmentDTO("segment-1", 0, 1_000, "hello", "en")],
    )
    subtitles.save_translated_segments(
        project.project_id,
        project.target_language,
        [SubtitleSegmentDTO("segment-1", 0, 1_000, "你好", "zh-CN")],
    )
    usecase = ReviseSubtitleTranslation(
        project_repository=projects,
        task_repository=tasks,
        subtitle_repository=subtitles,
        translator=UnusedTranslator(),
        subtitle_writer=SrtWriter(),
    )

    # act：保存编辑后重新创建连接对象，模拟应用退出再启动。
    result = usecase.save_edit(
        EditSubtitleTranslationInput(
            project_id=project.project_id,
            segment_id="segment-1",
            translated_text="你好，课程",
        )
    )
    reopened = SQLiteSubtitleRepository(SQLiteDatabase(database_path))
    restored = reopened.get_translated_segments(
        project.project_id,
        project.target_language,
    )

    # assert：结构化数据和 `SRT` 正文都采用修订后的译文。
    assert [segment.text for segment in restored] == ["你好，课程"]
    assert "你好，课程" in result.subtitle_path.read_text(encoding="utf-8")
