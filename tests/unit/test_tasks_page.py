"""任务页面逐句翻译展示的单元测试。"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QGridLayout, QMessageBox, QSplitter

from core.domain.entities import Project, Task
from core.domain.enums import ExportMode, TaskCheckpoint
from core.dto.subtitle_dto import (
    SubtitleSegmentDTO,
    TranslationFailureDTO,
    TranslationProgressDTO,
)
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


def test_tasks_page_never_blocks_new_submission_by_active_task_count() -> None:
    """活动任务再多也不能禁用创建入口，高资源步骤由调度器排队。"""

    app = QApplication.instance() or QApplication([])
    page = TasksPage(TaskService())

    # act：分别模拟未达到和达到旧并发配置值的两种状态。
    page.set_project_operation_capacity(active_count=1, max_concurrency=2)
    assert page.create_task_button.isEnabled() is True
    assert page.concurrency_label.text() == "后台 1（创建不限量）"

    page.set_project_operation_capacity(active_count=2, max_concurrency=2)

    # assert：达到旧上限后仍可创建和刷新，不把排队任务挡在页面外。
    assert page.create_task_button.isEnabled() is True
    assert page.refresh_button.isEnabled() is True
    assert page.concurrency_label.text() == "后台 2（创建不限量）"
    page.deleteLater()
    app.processEvents()


def test_tasks_page_explains_recognition_parallelism() -> None:
    """任务页应展示识别并发上限，并说明下载成品独立排队。"""

    app = QApplication.instance() or QApplication([])
    page = TasksPage(TaskService())

    page.set_project_operation_capacity(
        active_count=0,
        max_concurrency=2,
        recognition_parallelism=3,
    )

    policy_text = page.resource_policy_label.text()
    assert "同时 3 个" in policy_text
    assert "下载成品独立排队" in policy_text
    page.deleteLater()
    app.processEvents()


def test_tasks_page_keeps_download_enabled_while_other_video_is_processing(
    tmp_path,
) -> None:
    """其他视频正在识别时，当前项目的下载按钮不应被锁死。"""

    app = QApplication.instance() or QApplication([])
    projects = InMemoryProjectRepository()
    tasks = InMemoryTaskRepository()
    subtitles = InMemorySubtitleRepository()
    project = Project(
        project_id="project-ready",
        source_video=tmp_path / "ready.mp4",
        source_language="en",
        target_language="zh-CN",
        workspace_dir=tmp_path / "project-ready",
    )
    project.mark_completed()
    projects.save(project)
    completed = Task("task-ready", project.project_id, "translate_subtitles")
    completed.mark_succeeded("翻译完成", TaskCheckpoint.TRANSLATED)
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

    page.refresh_history()
    assert page.download_button.isEnabled() is True

    # 另一个视频正在识别，只影响它自己，不应影响当前项目的下载入口。
    page.set_project_operation_capacity(
        active_count=1,
        max_concurrency=2,
        active_project_ids={"project-other"},
    )

    assert page.download_button.isEnabled() is True
    page.deleteLater()
    app.processEvents()


def test_tasks_page_disables_download_only_while_same_video_exports(
    tmp_path,
) -> None:
    """同一个视频正在导出成品时才临时禁用下载，结束后立即恢复。"""

    app = QApplication.instance() or QApplication([])
    projects = InMemoryProjectRepository()
    tasks = InMemoryTaskRepository()
    subtitles = InMemorySubtitleRepository()
    project = Project(
        project_id="project-exporting",
        source_video=tmp_path / "exporting.mp4",
        source_language="en",
        target_language="zh-CN",
        workspace_dir=tmp_path / "project-exporting",
    )
    project.mark_completed()
    projects.save(project)
    completed = Task("task-exporting", project.project_id, "translate_subtitles")
    completed.mark_succeeded("翻译完成", TaskCheckpoint.TRANSLATED)
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

    page.refresh_history()
    page.set_project_operation_capacity(
        active_count=1,
        max_concurrency=2,
        exporting_project_ids={project.project_id},
    )
    assert page.download_button.isEnabled() is False

    # 导出线程退出后应恢复可点，允许再次下载同一个项目。
    page.set_project_operation_capacity(
        active_count=0,
        max_concurrency=2,
        exporting_project_ids=set(),
    )
    assert page.download_button.isEnabled() is True
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
    emitted: list[list[tuple[str, str]]] = []
    page.delete_requested.connect(emitted.append)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    page.refresh_history()
    assert page.delete_button.isEnabled() is True
    page.delete_button.click()
    app.processEvents()

    assert emitted == [[(project.project_id, str(project.workspace_dir))]]
    page.deleteLater()
    app.processEvents()


def test_tasks_page_allows_deleting_completed_project_with_prepared_product(
    tmp_path,
    monkeypatch,
) -> None:
    """已完成且成品已生成的视频也必须能删除。

    回归背景：`_sync_project_actions` 曾在设置下载按钮提示时提前返回，
    把删除按钮的启用代码放在了 `return` 之后。已完成任务通常正好命中
    “成品已在任务目录生成”分支，删除按钮因此永久停留在构造时的禁用状态，
    用户看不到任何报错，只觉得任务删不掉。
    """

    # arrange：构造已完成项目，并让内部成品文件真实存在。
    app = QApplication.instance() or QApplication([])
    projects = InMemoryProjectRepository()
    tasks = InMemoryTaskRepository()
    prepared = tmp_path / "project-completed-delete" / "exports" / "product.mp4"
    prepared.parent.mkdir(parents=True)
    prepared.write_bytes(b"fake-video")
    project = Project(
        project_id="project-completed-delete",
        source_video=tmp_path / "completed.mp4",
        source_language="en",
        target_language="zh-CN",
        workspace_dir=tmp_path / "project-completed-delete",
        prepared_output_path=prepared,
    )
    project.mark_completed()
    projects.save(project)
    completed = Task(
        "task-completed-delete",
        project.project_id,
        "translate_subtitles",
    )
    completed.mark_succeeded("翻译完成", TaskCheckpoint.TRANSLATED)
    tasks.save(completed)
    page = TasksPage(
        TaskService(project_repository=projects, task_repository=tasks)
    )
    emitted: list[list[tuple[str, str]]] = []
    page.delete_requested.connect(emitted.append)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    # act：刷新历史选中该项目后直接点击删除。
    page.refresh_history()
    assert page.delete_button.isEnabled() is True
    page.delete_button.click()
    app.processEvents()

    # assert：删除意图携带项目编号和项目目录，交给主窗口执行真实清理。
    assert emitted == [[(project.project_id, str(project.workspace_dir))]]
    page.deleteLater()
    app.processEvents()


def test_tasks_page_allows_deleting_completed_project_while_exporting(
    tmp_path,
    monkeypatch,
) -> None:
    """成品正在导出时删除按钮同样不能被下载逻辑连坐禁用。

    这里不准备预生成成品，专门覆盖“导出中”这个提前返回分支。
    """

    app = QApplication.instance() or QApplication([])
    projects = InMemoryProjectRepository()
    tasks = InMemoryTaskRepository()
    project = Project(
        project_id="project-exporting-delete",
        source_video=tmp_path / "exporting.mp4",
        source_language="en",
        target_language="zh-CN",
        workspace_dir=tmp_path / "project-exporting-delete",
    )
    project.mark_completed()
    projects.save(project)
    completed = Task(
        "task-exporting-delete",
        project.project_id,
        "export_video",
    )
    completed.mark_succeeded("下载完成", TaskCheckpoint.EXPORTED)
    tasks.save(completed)
    page = TasksPage(
        TaskService(project_repository=projects, task_repository=tasks)
    )
    emitted: list[list[tuple[str, str]]] = []
    page.delete_requested.connect(emitted.append)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    page.refresh_history()
    # 模拟主窗口广播“该项目正在生成成品”的容量状态。
    page.set_project_operation_capacity(
        active_count=1,
        max_concurrency=1,
        exporting_project_ids={project.project_id},
    )
    assert page.delete_button.isEnabled() is True
    page.delete_button.click()
    app.processEvents()

    assert emitted == [[(project.project_id, str(project.workspace_dir))]]
    page.deleteLater()
    app.processEvents()


def test_tasks_page_deletes_multiple_selected_tasks_in_one_action(
    tmp_path,
    monkeypatch,
) -> None:
    """按住 Ctrl 多选后，删除按钮应一次性提交全部选中任务。"""

    app = QApplication.instance() or QApplication([])
    projects = InMemoryProjectRepository()
    tasks = InMemoryTaskRepository()
    for index in (1, 2, 3):
        project = Project(
            project_id=f"project-batch-{index}",
            source_video=tmp_path / f"batch-{index}.mp4",
            source_language="en",
            target_language="zh-CN",
            workspace_dir=tmp_path / f"project-batch-{index}",
        )
        project.mark_processing()
        projects.save(project)
        running = Task(f"task-batch-{index}", project.project_id, "translate_subtitles")
        running.start("正在翻译")
        tasks.save(running)

    page = TasksPage(
        TaskService(project_repository=projects, task_repository=tasks)
    )
    emitted: list[list[tuple[str, str]]] = []
    page.delete_requested.connect(emitted.append)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    page.refresh_history()
    # 复选第一项和第三项，中间一项保持不选。
    page.task_list.setCurrentRow(0)
    page.task_list.selectionModel().select(
        page.task_list.model().index(2, 0),
        page.task_list.selectionModel().SelectionFlag.Select,
    )
    page.delete_button.click()
    app.processEvents()

    assert emitted == [
        [
            ("project-batch-1", str(tmp_path / "project-batch-1")),
            ("project-batch-3", str(tmp_path / "project-batch-3")),
        ]
    ]
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


def test_tasks_page_lists_failed_subtitles_and_jumps_to_them(tmp_path) -> None:
    """翻译失败清单应展示失败原因，点击后跳到主列表中的同一条字幕。"""

    app = QApplication.instance() or QApplication([])
    projects = InMemoryProjectRepository()
    tasks = InMemoryTaskRepository()
    subtitles = InMemorySubtitleRepository()
    project = Project(
        project_id="project-failure",
        source_video=tmp_path / "failure.mp4",
        source_language="en",
        target_language="zh-CN",
        workspace_dir=tmp_path / "project-failure",
    )
    project.mark_completed()
    projects.save(project)
    completed = Task("task-failure", project.project_id, "translate_subtitles")
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
        [SubtitleSegmentDTO("segment-1", 0, 1_000, "你好", "zh-CN")],
    )
    subtitles.save_translation_failure(
        TranslationFailureDTO(
            project_id=project.project_id,
            segment_id="segment-2",
            target_language=project.target_language,
            error_message="HTTP 503",
        )
    )
    page = TasksPage(
        TaskService(
            project_repository=projects,
            task_repository=tasks,
            subtitle_repository=subtitles,
        )
    )

    page.refresh_history()
    app.processEvents()

    assert page.failed_subtitle_list.count() == 1
    assert "HTTP 503" in page.failed_subtitle_list.item(0).text()
    assert "共 1 条字幕翻译失败" in page.failure_count_label.text()
    # 存在失败字幕时不应允许直接导出，下载按钮保持关闭。
    assert page.download_button.isEnabled() is False

    # `itemClicked` 只在真实点击时发出，测试里用 Qt 自带的点击模拟触发。
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    QTest.mouseClick(
        page.failed_subtitle_list.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        page.failed_subtitle_list.visualItemRect(
            page.failed_subtitle_list.item(0)
        ).center(),
    )
    app.processEvents()

    assert page.subtitle_list.currentRow() == 1
    assert page.subtitle_source_text.toPlainText() == "world"
    assert "已定位到第 2 条失败字幕" in page.subtitle_feedback_label.text()
    page.deleteLater()
    app.processEvents()


def test_tasks_page_hides_failure_group_when_translation_is_complete(
    tmp_path,
) -> None:
    """全部翻译成功时不占用界面空间展示失败清单。"""

    app = QApplication.instance() or QApplication([])
    projects = InMemoryProjectRepository()
    tasks = InMemoryTaskRepository()
    subtitles = InMemorySubtitleRepository()
    project = Project(
        project_id="project-no-failure",
        source_video=tmp_path / "clean.mp4",
        source_language="en",
        target_language="zh-CN",
        workspace_dir=tmp_path / "project-no-failure",
    )
    project.mark_completed()
    projects.save(project)
    completed = Task("task-no-failure", project.project_id, "translate_subtitles")
    completed.mark_succeeded("翻译完成", TaskCheckpoint.TRANSLATED)
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

    page.refresh_history()
    app.processEvents()

    assert page.failed_subtitle_list.count() == 0
    assert page.failure_group.isVisible() is False
    assert page.download_button.isEnabled() is True
    page.deleteLater()
    app.processEvents()


def test_tasks_page_marks_ready_burn_in_product_on_download_button(
    tmp_path,
) -> None:
    """任务目录里已经有成品时，下载按钮应提示可以直接保存。"""

    app = QApplication.instance() or QApplication([])
    projects = InMemoryProjectRepository()
    tasks = InMemoryTaskRepository()
    subtitles = InMemorySubtitleRepository()
    prepared_path = tmp_path / "project-ready" / "exports" / "video-烧录成品.mp4"
    prepared_path.parent.mkdir(parents=True)
    prepared_path.write_bytes(b"burned video")
    project = Project(
        project_id="project-ready",
        source_video=tmp_path / "video.mp4",
        source_language="en",
        target_language="zh-CN",
        workspace_dir=tmp_path / "project-ready",
        export_mode=ExportMode.BURN_IN,
        prepared_output_path=prepared_path,
    )
    project.mark_completed()
    projects.save(project)
    tasks.save(Task("task-ready", project.project_id, "translate_subtitles"))
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

    page.refresh_history()
    app.processEvents()

    assert page.download_button.isEnabled() is True
    assert "已在任务目录生成" in page.download_button.toolTip()

    # 成品被删除后，界面必须回到“需要重新生成”的说法。
    prepared_path.unlink()
    page.set_project_operation_capacity(
        active_count=0,
        max_concurrency=1,
        active_project_ids=set(),
        exporting_project_ids=set(),
    )
    app.processEvents()
    assert "已在任务目录生成" not in page.download_button.toolTip()
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
