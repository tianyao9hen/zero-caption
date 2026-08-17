"""任务页面逐句翻译展示的单元测试。"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QGridLayout, QMessageBox, QSplitter

from core.domain.entities import Project, Task
from core.domain.enums import ExportMode, TaskCheckpoint
from core.dto.subtitle_dto import SubtitleSegmentDTO, TranslationProgressDTO
from core.dto.task_dto import TaskSummaryDTO
from core.services.task_service import TaskService
from infrastructure.storage.memory_repositories import (
    InMemoryProjectRepository,
    InMemorySubtitleRepository,
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

    assert page.translation_count_label.text() == "已完成 1/2 条"
    assert page.subtitle_list.count() == 1
    assert "原文：hello" in page.subtitle_list.item(0).text()
    assert "译文：你好" in page.subtitle_list.item(0).text()
    translation_splitter = page.findChild(
        QSplitter,
        "subtitleTranslationSplitter",
    )
    assert translation_splitter is not None
    assert translation_splitter.orientation() is Qt.Orientation.Horizontal
    details_grid = page.findChild(QGridLayout, "taskDetailsGrid")
    assert details_grid is not None
    assert details_grid.rowCount() == 6
    assert details_grid.columnCount() == 6
    assert 200 <= page.subtitle_list.minimumHeight() <= 220
    assert page.subtitle_source_text.minimumHeight() <= 72
    assert page.subtitle_translation_editor.minimumHeight() <= 100
    assert page.message_label.maximumHeight() <= 48
    assert page.error_label.maximumHeight() <= 48
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


def test_tasks_page_displays_random_suffix_from_project_directory(tmp_path) -> None:
    """新项目列表名称应展示目录中的两位后缀，方便区分同一视频的任务。"""

    app = QApplication.instance() or QApplication([])
    projects = InMemoryProjectRepository()
    tasks = InMemoryTaskRepository()
    project = Project(
        project_id="project-readable-name",
        source_video=tmp_path / "lesson.mp4",
        source_language="en",
        target_language="zh-CN",
        workspace_dir=tmp_path / "data" / "projects" / "lesson-AB",
    )
    project.mark_processing()
    projects.save(project)
    task = Task("task-readable-name", project.project_id, "transcribe_video")
    task.start("开始识别")
    tasks.save(task)
    page = TasksPage(
        TaskService(project_repository=projects, task_repository=tasks)
    )

    page.refresh_history()
    app.processEvents()

    assert page.task_list.item(0).text().splitlines()[0] == "lesson-AB.mp4"
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


def test_tasks_page_disables_new_submission_only_when_capacity_is_full() -> None:
    """已有任务运行时仍可继续创建，达到普通并发上限后才禁用入口。"""

    app = QApplication.instance() or QApplication([])
    page = TasksPage(TaskService())

    # act：第一个任务运行时仍有第二个槽位，第二个任务提交后容量耗尽。
    page.set_project_operation_capacity(active_count=1, max_concurrency=2)
    assert page.create_task_button.isEnabled() is True
    assert page.concurrency_label.text() == "后台 1/2"
    assert "自动排队串行执行" in page.resource_policy_label.text()

    page.set_project_operation_capacity(active_count=2, max_concurrency=2)

    # assert：创建入口暂停，但用户仍可刷新并查看交错更新的任务历史。
    assert page.create_task_button.isEnabled() is False
    assert page.refresh_button.isEnabled() is True
    assert page.concurrency_label.text() == "后台 2/2"
    page.deleteLater()
    app.processEvents()


def test_tasks_page_does_not_steal_selection_for_another_task_progress(
    tmp_path,
) -> None:
    """未选中任务的实时事件应更新列表，但不切换用户正在查看的视频。"""

    app = QApplication.instance() or QApplication([])
    projects = InMemoryProjectRepository()
    tasks = InMemoryTaskRepository()
    for index in (1, 2):
        project = Project(
            project_id=f"project-{index}",
            source_video=tmp_path / f"video-{index}.mp4",
            source_language="en",
            target_language="zh-CN",
            workspace_dir=tmp_path / f"project-{index}",
        )
        project.mark_processing()
        projects.save(project)
        running = Task(
            f"task-{index}",
            project.project_id,
            "translate_subtitles",
        )
        running.start("开始翻译")
        tasks.save(running)

    page = TasksPage(
        TaskService(project_repository=projects, task_repository=tasks)
    )
    page.refresh_history()
    selected_item = page._find_project_item("project-1")
    assert selected_item is not None
    page.task_list.setCurrentItem(selected_item)

    # act：另一个视频发布新进度，模拟两个后台线程交错上报。
    page.update_summary(
        TaskSummaryDTO(
            task_id="task-2",
            task_type="translate_subtitles",
            status="running",
            progress=75,
            current_step="逐句翻译 3/4",
            message="已翻译第 3 条字幕",
            project_id="project-2",
        )
    )
    app.processEvents()

    # assert：第二个条目更新为 75%，右侧仍保持第一个项目。
    other_item = page._find_project_item("project-2")
    assert other_item is not None
    assert "75%" in other_item.text()
    assert page.task_list.currentItem() is selected_item
    assert page.project_id_label.text() == "project-1"
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
    assert "已完成 · 40%" in summary
    assert "处理中 · 100%" not in summary
    page.deleteLater()
    app.processEvents()


def test_tasks_page_allows_deleting_running_project(
    tmp_path,
    monkeypatch,
) -> None:
    """运行中项目也应启用删除入口，并提交项目编号与项目目录。"""

    app = QApplication.instance() or QApplication([])
    projects = InMemoryProjectRepository()
    tasks = InMemoryTaskRepository()
    project = Project(
        project_id="project-running-delete",
        source_video=tmp_path / "running.mp4",
        source_language="en",
        target_language="zh-CN",
        workspace_dir=tmp_path / "project-running-delete",
    )
    project.mark_processing()
    projects.save(project)
    running = Task("task-running-delete", project.project_id, "translate_subtitles")
    running.start("正在翻译")
    tasks.save(running)
    page = TasksPage(
        TaskService(project_repository=projects, task_repository=tasks)
    )
    emitted: list[tuple[str, str]] = []
    page.delete_requested.connect(
        lambda project_id, workspace_dir: emitted.append(
            (project_id, workspace_dir)
        )
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    page.refresh_history()
    assert page.delete_button.isEnabled() is True
    page.delete_button.click()
    app.processEvents()

    assert emitted == [(project.project_id, str(project.workspace_dir))]
    page.deleteLater()
    app.processEvents()


def test_tasks_page_selects_translation_and_emits_edit_and_retranslate_requests(
    tmp_path,
) -> None:
    """用户应能选中指定字幕，编辑译文并明确请求只重译这一条。"""

    # arrange：准备两条持久化字幕，让页面通过核心服务加载而不是手工塞控件。
    app = QApplication.instance() or QApplication([])
    projects = InMemoryProjectRepository()
    tasks = InMemoryTaskRepository()
    subtitles = InMemorySubtitleRepository()
    project = Project(
        project_id="project-edit",
        source_video=tmp_path / "edit.mp4",
        source_language="en",
        target_language="zh-CN",
        workspace_dir=tmp_path / "project-edit",
    )
    project.mark_completed()
    projects.save(project)
    completed = Task("task-edit", project.project_id, "translate_subtitles")
    completed.mark_succeeded("翻译完成", TaskCheckpoint.TRANSLATED)
    tasks.save(completed)
    subtitles.save_source_segments(
        project.project_id,
        [
            SubtitleSegmentDTO("segment-1", 0, 1_000, "hello", "en"),
            SubtitleSegmentDTO("segment-2", 1_000, 2_000, "world", "en"),
        ],
    )
    subtitles.save_translated_segments(
        project.project_id,
        project.target_language,
        [
            SubtitleSegmentDTO("segment-1", 0, 1_000, "你好", "zh-CN"),
            SubtitleSegmentDTO("segment-2", 1_000, 2_000, "世界", "zh-CN"),
        ],
    )
    page = TasksPage(
        TaskService(
            project_repository=projects,
            task_repository=tasks,
            subtitle_repository=subtitles,
        )
    )
    edit_requests: list[tuple[str, str, str]] = []
    retranslate_requests: list[tuple[str, str]] = []
    page.save_translation_requested.connect(
        lambda project_id, segment_id, text: edit_requests.append(
            (project_id, segment_id, text)
        )
    )
    page.retranslate_requested.connect(
        lambda project_id, segment_id: retranslate_requests.append(
            (project_id, segment_id)
        )
    )

    # act：加载项目、选择第二条、修改文本，再分别点击两个显式操作按钮。
    page.refresh_history()
    page.subtitle_list.setCurrentRow(1)
    page.subtitle_translation_editor.setPlainText("手工修订后的世界")
    page.save_translation_button.click()
    page.retranslate_button.click()
    app.processEvents()

    # assert：信号携带稳定字幕编号，不依赖容易变化的界面行号。
    assert page.subtitle_list.count() == 2
    assert page.subtitle_source_text.toPlainText() == "world"
    assert edit_requests == [
        (project.project_id, "segment-2", "手工修订后的世界")
    ]
    assert retranslate_requests == [(project.project_id, "segment-2")]

    page.deleteLater()
    app.processEvents()


def test_tasks_page_emits_retry_for_failed_project(tmp_path) -> None:
    """失败项目应显示继续入口，并提交项目编号和原处理模式。"""

    app = QApplication.instance() or QApplication([])
    projects = InMemoryProjectRepository()
    tasks = InMemoryTaskRepository()
    project = Project(
        project_id="project-retry",
        source_video=tmp_path / "retry.mp4",
        source_language="en",
        target_language="zh-CN",
        workspace_dir=tmp_path / "project-retry",
    )
    project.mark_failed("模拟翻译失败")
    projects.save(project)
    failed = Task("task-retry", project.project_id, "translate_subtitles")
    failed.mark_failed("模拟翻译失败")
    tasks.save(failed)
    page = TasksPage(
        TaskService(project_repository=projects, task_repository=tasks)
    )
    emitted: list[tuple[str, str]] = []
    page.retry_requested.connect(
        lambda project_id, mode: emitted.append((project_id, mode))
    )

    page.refresh_history()
    page.retry_button.click()
    app.processEvents()

    assert page.retry_button.isEnabled() is True
    assert emitted == [(project.project_id, "full_pipeline")]
    page.deleteLater()
    app.processEvents()


def test_tasks_page_download_chooses_directory_and_keeps_source_video(
    tmp_path,
    monkeypatch,
) -> None:
    """完整译文项目应在点击下载后选择目录并生成安全的新文件名。"""

    app = QApplication.instance() or QApplication([])
    projects = InMemoryProjectRepository()
    tasks = InMemoryTaskRepository()
    subtitles = InMemorySubtitleRepository()
    project = Project(
        project_id="project-reexport",
        source_video=tmp_path / "reexport.mp4",
        source_language="en",
        target_language="zh-CN",
        workspace_dir=tmp_path / "project-reexport",
        output_path=tmp_path / "old-results" / "reexport.mp4",
    )
    project.mark_completed()
    projects.save(project)
    completed = Task("task-reexport", project.project_id, "export_video")
    completed.mark_succeeded("导出完成", TaskCheckpoint.EXPORTED)
    tasks.save(completed)
    subtitles.save_source_segments(
        project.project_id,
        [SubtitleSegmentDTO("segment-1", 0, 1_000, "hello", "en")],
    )
    subtitles.save_translated_segments(
        project.project_id,
        project.target_language,
        [SubtitleSegmentDTO("segment-1", 0, 1_000, "你好", "zh-CN")],
    )
    page = TasksPage(
        TaskService(
            project_repository=projects,
            task_repository=tasks,
            subtitle_repository=subtitles,
        )
    )
    emitted: list[tuple[str, str, str]] = []
    page.download_requested.connect(
        lambda project_id, mode, output_path: emitted.append(
            (project_id, mode, output_path)
        )
    )

    page.refresh_history()
    burn_in_index = page.export_mode_combo.findData(ExportMode.BURN_IN.value)
    page.export_mode_combo.setCurrentIndex(burn_in_index)
    selected_directory = tmp_path / "new-results"
    selected_directory.mkdir()
    monkeypatch.setattr(
        "ui.pages.tasks_page.QFileDialog.getExistingDirectory",
        lambda *_args, **_kwargs: str(selected_directory),
    )
    page.download_button.click()
    app.processEvents()

    selected_output = selected_directory / "reexport-字幕.mp4"
    assert page.download_button.isEnabled() is True
    assert project.source_video == tmp_path / "reexport.mp4"
    assert emitted == [
        (
            project.project_id,
            ExportMode.BURN_IN.value,
            str(selected_output),
        )
    ]
    page.deleteLater()
    app.processEvents()
