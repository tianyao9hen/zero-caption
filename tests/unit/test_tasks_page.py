"""任务页面逐句翻译展示的单元测试。"""

from PySide6.QtWidgets import QApplication

from core.domain.entities import Project, Task
from core.domain.enums import TaskCheckpoint
from core.dto.subtitle_dto import TranslationProgressDTO
from core.dto.task_dto import TaskSummaryDTO
from core.services.task_service import TaskService
from infrastructure.storage.memory_repositories import (
    InMemoryProjectRepository,
    InMemoryTaskRepository,
)
from ui.pages.tasks_page import TasksPage


def test_tasks_page_appends_translation_progress_in_real_time(monkeypatch) -> None:
    """每条翻译事件应追加原文和译文，并更新当前完成数量。"""

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    page = TasksPage(TaskService())
    progress = TranslationProgressDTO(
        task_id="task-1",
        current_index=1,
        total_segments=2,
        source_text="hello",
        translated_text="你好",
    )

    page.update_translation_progress(progress)
    app.processEvents()

    preview = page.translation_preview.toPlainText()
    assert page.translation_count_label.text() == "已完成 1/2 条"
    assert "原文：hello" in preview
    assert "译文：你好" in preview
    page.deleteLater()
    app.processEvents()


def test_tasks_page_groups_persisted_steps_by_video_project(tmp_path) -> None:
    """同一视频的多个内部步骤应聚合成一个可选择的任务条目。"""

    app = QApplication.instance() or QApplication([])
    projects = InMemoryProjectRepository()
    tasks = InMemoryTaskRepository()
    project = Project(
        project_id="project-1",
        source_video=tmp_path / "lesson.mp4",
        source_language="en",
        target_language="zh-CN",
        workspace_dir=tmp_path / "project-1",
    )
    project.mark_processing()
    projects.save(project)

    imported = Task("task-import", project.project_id, "create_project")
    imported.mark_succeeded("项目已导入", TaskCheckpoint.IMPORTED)
    translating = Task("task-translate", project.project_id, "translate_subtitles")
    translating.update_progress(
        65,
        "逐句翻译 2/5",
        TaskCheckpoint.TRANSCRIBED,
        "已翻译第 2 条字幕",
    )
    tasks.save(imported)
    tasks.save(translating)
    service = TaskService(
        project_repository=projects,
        task_repository=tasks,
    )
    page = TasksPage(service)

    # act：刷新历史后，再模拟同一项目收到一个新的实时进度事件。
    page.refresh_history()
    page.update_summary(
        TaskSummaryDTO(
            task_id="task-translate",
            task_type="translate_subtitles",
            status="running",
            progress=80,
            current_step="逐句翻译 4/5",
            message="已翻译第 4 条字幕",
            project_id=project.project_id,
        )
    )
    app.processEvents()

    # assert：列表仍只有一个视频条目，右侧详情和列表摘要同步更新。
    assert page.task_list.count() == 1
    assert "lesson.mp4" in page.task_list.item(0).text()
    assert "80%" in page.task_list.item(0).text()
    assert page.project_id_label.text() == project.project_id
    assert page.task_type_label.text() == "逐句翻译"
    assert page.progress_bar.value() == 80

    page.deleteLater()
    app.processEvents()


def test_tasks_page_create_button_emits_request_signal() -> None:
    """任务页创建按钮只应发出交互信号，不在页面中直接启动业务流程。"""

    app = QApplication.instance() or QApplication([])
    page = TasksPage(TaskService())
    emitted: list[bool] = []
    page.create_requested.connect(lambda: emitted.append(True))

    page.create_task_button.click()
    app.processEvents()

    assert emitted == [True]
    page.deleteLater()
    app.processEvents()


def test_tasks_page_prefers_completed_step_over_stale_processing_project(
    tmp_path,
) -> None:
    """旧项目总状态未收口时，列表不应显示自相矛盾的处理中 100%。"""

    app = QApplication.instance() or QApplication([])
    projects = InMemoryProjectRepository()
    tasks = InMemoryTaskRepository()
    project = Project(
        project_id="project-legacy",
        source_video=tmp_path / "legacy.mp4",
        source_language="auto",
        target_language="zh-CN",
        workspace_dir=tmp_path / "legacy",
    )
    project.mark_processing()
    projects.save(project)
    transcription = Task(
        "task-transcription",
        project.project_id,
        "transcribe_video",
    )
    transcription.mark_succeeded("识别完成", TaskCheckpoint.TRANSCRIBED)
    tasks.save(transcription)
    page = TasksPage(
        TaskService(project_repository=projects, task_repository=tasks)
    )

    page.refresh_history()
    app.processEvents()

    summary = page.task_list.item(0).text()
    assert "已完成 · 100%" in summary
    assert "处理中 · 100%" not in summary
    page.deleteLater()
    app.processEvents()
