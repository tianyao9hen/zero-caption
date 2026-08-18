"""主窗口构造烟测，保护启动装配和页面栈不会在创建时崩溃。"""

import logging
from pathlib import Path
from threading import Event, Lock
from time import monotonic

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from app.container import AppContainer
from config.settings import EngineSettings, RuntimeSettings, Settings, TaskSettings
from core.domain.entities import Project, Task
from core.domain.enums import TaskCheckpoint
from core.dto.asr_dto import AsrHardwareInfoDTO
from core.dto.subtitle_dto import SubtitleSegmentDTO
from infrastructure.logging.setup import configure_logging
from infrastructure.storage.workspace import WorkspaceManager


def cpu_hardware_info() -> AsrHardwareInfoDTO:
    """让窗口烟测固定走不依赖 GPU 的 `small + CPU` 路径。"""

    return AsrHardwareInfoDTO.cpu_only("测试固定使用 CPU。")


def test_main_window_can_be_created_offscreen(tmp_path, monkeypatch) -> None:
    """在无显示器环境中创建主窗口，验证 Qt 控件和依赖注入已接通。"""

    # arrange：离屏平台避免测试依赖 Windows 桌面当前显示器。
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    workspace = WorkspaceManager(tmp_path / "workspace")
    workspace.ensure_structure()
    settings = Settings(workspace_root=workspace.root)
    container = AppContainer(
        settings=settings,
        workspace=workspace,
        logger=logging.getLogger("test-main-window"),
        asr_hardware_info=cpu_hardware_info(),
    )

    # act：通过容器创建完整主窗口，而不是手工绕过装配层。
    window = container.create_main_window()

    # assert：窗口使用更紧凑的默认尺寸，页眉元素位于同一个横向布局。
    assert window.windowTitle() == "Zero Caption"
    assert window.windowIcon().isNull() is False
    assert window.brand_logo.pixmap().isNull() is False
    assert window.size().width() == 1100
    assert window.size().height() == 680
    header = window.findChild(QWidget, "applicationHeader")
    assert header is not None
    assert header.layout().indexOf(window.brand_logo) >= 0
    assert header.layout().indexOf(window.navigation) >= 0
    assert header.layout().indexOf(window.import_button) >= 0
    assert window.projects_page is not None
    assert window.tasks_page is not None
    assert window.navigation.projects_button.isChecked() is True
    assert window.task_service.resource_scheduler is container.resource_scheduler

    # act：程序化切换任务工作区时，页面栈和导航选中状态应同步。
    window.navigation.set_current_page(1)
    app.processEvents()

    assert window.stack.currentWidget() is window.tasks_page
    assert window.navigation.tasks_button.isChecked() is True
    assert window.tasks_page.create_task_button.text() == "新建任务"
    window.close()
    window.deleteLater()
    app.processEvents()


def test_main_window_downloads_completed_translation_without_changing_source(
    tmp_path,
    monkeypatch,
) -> None:
    """下载按钮应在用户选定目录后生成新文件，并保留原视频内容。"""

    # arrange：准备一个已经完成翻译的项目，下载走真实窗口信号和外挂导出器，
    # 但不需要启动识别模型、翻译网络请求或 `FFmpeg`。
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    workspace = WorkspaceManager(tmp_path / "workspace")
    workspace.ensure_structure()
    container = AppContainer(
        settings=Settings(workspace_root=workspace.root),
        workspace=workspace,
        logger=logging.getLogger("test-window-download"),
        asr_hardware_info=cpu_hardware_info(),
    )
    source_video = tmp_path / "lesson.mp4"
    source_content = b"original video content"
    source_video.write_bytes(source_content)
    project_id = "project-window-download"
    project_dir = workspace.create_project_structure(
        project_id,
        "lesson-DL",
    )
    project = Project(
        project_id=project_id,
        source_video=source_video,
        source_language="en",
        target_language="zh-CN",
        workspace_dir=project_dir,
    )
    project.mark_completed()
    container.project_repository.save(project)
    task = Task("task-window-download", project.project_id, "translate_subtitles")
    task.mark_succeeded("翻译完成", TaskCheckpoint.TRANSLATED)
    container.task_repository.save(task)
    container.subtitle_repository.save_source_segments(
        project.project_id,
        [SubtitleSegmentDTO("segment-1", 0, 1_000, "hello", "en")],
    )
    container.subtitle_repository.save_translated_segments(
        project.project_id,
        project.target_language,
        [SubtitleSegmentDTO("segment-1", 0, 1_000, "你好", "zh-CN")],
    )
    download_directory = tmp_path / "downloads"
    download_directory.mkdir()
    monkeypatch.setattr(
        "ui.pages.tasks_page.QFileDialog.getExistingDirectory",
        lambda *_args, **_kwargs: str(download_directory),
    )
    window = container.create_main_window()

    # act：通过任务页按钮发出下载请求，并等待后台导出线程结束。
    window.navigation.set_current_page(1)
    assert window.tasks_page.download_button.isEnabled() is True
    window.tasks_page.download_button.click()
    deadline = monotonic() + 3
    while window._pipeline_runners and monotonic() < deadline:
        app.processEvents()

    # assert：外挂模式只下载字幕，原视频既不复制也不被覆盖或改写。
    output_video = download_directory / "lesson-字幕.mp4"
    output_subtitle = download_directory / "lesson-字幕.srt"
    assert window._pipeline_runners == {}
    assert output_video.exists() is False
    assert "你好" in output_subtitle.read_text(encoding="utf-8")
    assert source_video.read_bytes() == source_content
    assert "下载完成" in window.status_widget.label.text()
    assert str(output_subtitle) in window.status_widget.label.text()

    window.close()
    window.deleteLater()
    app.processEvents()


def test_main_window_accepts_more_video_operations_than_configured_capacity(
    tmp_path,
    monkeypatch,
) -> None:
    """主窗口不应把旧并发配置当成视频任务创建数量限制。"""

    # arrange：三个操作都等待同一个事件，确保断言时线程仍处于运行状态。
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    workspace = WorkspaceManager(tmp_path / "workspace")
    workspace.ensure_structure()
    settings = Settings(
        workspace_root=workspace.root,
        task=TaskSettings(max_concurrency=2, max_heavy_concurrency=1),
    )
    container = AppContainer(
        settings=settings,
        workspace=workspace,
        logger=logging.getLogger("test-multiple-video-operations"),
        asr_hardware_info=cpu_hardware_info(),
    )
    window = container.create_main_window()
    release_operations = Event()
    all_started = Event()
    count_lock = Lock()
    started_count = 0

    def operation() -> object:
        """记录线程已经启动，然后等待测试统一放行。"""

        nonlocal started_count
        with count_lock:
            started_count += 1
            if started_count == 3:
                all_started.set()
        release_operations.wait(timeout=3)
        return object()

    # act：旧配置值是 2，但连续提交三个视频级操作也都应被接受。
    assert window._start_project_operation(operation, lambda _result: None, "任务一")
    assert window._start_project_operation(operation, lambda _result: None, "任务二")
    assert window._start_project_operation(operation, lambda _result: None, "任务三")
    deadline = monotonic() + 3
    while not all_started.is_set() and monotonic() < deadline:
        app.processEvents()

    # assert：三个线程都存活，两个创建入口仍然可用，后续任务可继续排队。
    assert all_started.is_set() is True
    assert len(window._pipeline_runners) == 3
    assert window.tasks_page.concurrency_label.text() == "后台 3（创建不限量）"
    assert window.tasks_page.create_task_button.isEnabled() is True
    assert window.import_button.isEnabled() is True

    # act：放行并等待三个线程释放，验证入口始终保持可用。
    release_operations.set()
    deadline = monotonic() + 3
    while window._pipeline_runners and monotonic() < deadline:
        app.processEvents()

    assert window._pipeline_runners == {}
    assert window.tasks_page.create_task_button.isEnabled() is True
    assert window.import_button.isEnabled() is True
    window.close()
    window.deleteLater()
    app.processEvents()


def test_main_window_refreshes_task_service_after_translation_settings_save(
    tmp_path,
    monkeypatch,
) -> None:
    """保存大模型设置后，后续任务应使用容器重新装配的新服务。"""

    # arrange：用临时写入函数截获设置，避免测试修改真实用户目录。
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    workspace = WorkspaceManager(tmp_path / "workspace")
    workspace.ensure_structure()
    saved_settings = []

    def save_to_temporary_file(settings):
        saved_settings.append(settings)
        return tmp_path / "settings.toml"

    monkeypatch.setattr(
        "app.container.save_engine_settings",
        save_to_temporary_file,
    )
    container = AppContainer(
        settings=Settings(workspace_root=workspace.root),
        workspace=workspace,
        logger=logging.getLogger("test-settings-refresh"),
        asr_hardware_info=cpu_hardware_info(),
    )
    window = container.create_main_window()
    original_service = window.task_service

    # act：连续编辑后等待自动保存，走完“页面 -> 主窗口 -> 容器 -> 重装配”路径。
    window.settings_page.base_url_field.setText("https://llm.example/v1")
    window.settings_page.model_field.setText("caption-model")
    window.settings_page.api_key_field.setText("configured-secret")
    window.settings_page.system_prompt_field.setPlainText("保存后的新系统提示词")
    QTest.qWait(650)

    # assert：配置已交给持久化入口，窗口和容器同时切换到新配置和新服务。
    assert len(saved_settings) == 1
    assert isinstance(saved_settings[0], EngineSettings)
    assert saved_settings[0].translation.api_key == "configured-secret"
    assert container.settings.engine.translation.model == "caption-model"
    assert container.settings.engine.translation.system_prompt == "保存后的新系统提示词"
    assert window.settings.engine.translation.base_url == "https://llm.example/v1"
    assert window.task_service is not original_service
    assert (
        window.task_service.translate_subtitles_usecase.translator.system_prompt
        == "保存后的新系统提示词"
    )
    assert "后续任务将使用新配置" in window.settings_page.feedback_label.text()

    window.close()
    window.deleteLater()
    app.processEvents()


def test_main_window_switches_workspace_and_deletes_old_directory_after_confirmation(
    tmp_path,
    monkeypatch,
) -> None:
    """应用工作区后应立即切换数据库，并只在用户选择“是”时删除旧目录。"""

    # arrange：所有目录和配置写入都限制在临时路径，确认框固定模拟用户选择“是”。
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    old_workspace = WorkspaceManager(tmp_path / "old-workspace")
    old_workspace.ensure_structure()
    old_root = old_workspace.root.resolve()
    saved_roots = []
    saved_model_caches = []
    logger = configure_logging(
        old_workspace.logs_dir,
        "INFO",
        logger=logging.getLogger("test-workspace-switch"),
    )

    def save_to_temporary_file(workspace_root, *, model_cache_dir=None):
        saved_roots.append(workspace_root)
        saved_model_caches.append(model_cache_dir)
        return tmp_path / "settings.toml"

    monkeypatch.setattr(
        "app.container.save_workspace_settings",
        save_to_temporary_file,
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args: QMessageBox.StandardButton.Yes,
    )
    container = AppContainer(
        settings=Settings(
            workspace_root=old_workspace.root,
            runtime=RuntimeSettings(model_cache_dir=old_workspace.root / "models"),
        ),
        workspace=old_workspace,
        logger=logger,
        asr_hardware_info=cpu_hardware_info(),
    )
    window = container.create_main_window()
    new_workspace = (tmp_path / "new-workspace").resolve()

    # act：通过真实设置页信号完成“应用 -> 重装配 -> 删除确认”链路。
    window.settings_page.workspace_field.setText(str(new_workspace))
    window.settings_page.workspace_apply_button.click()
    app.processEvents()

    # assert：当前对象、数据库、页面和持久化值都指向新工作区，旧目录已经删除。
    assert saved_roots == [new_workspace]
    assert saved_model_caches == [new_workspace / "models"]
    assert container.workspace.root == new_workspace
    assert container.settings.workspace_root == new_workspace
    assert container.settings.runtime.model_cache_dir == new_workspace / "models"
    assert container.database.path == new_workspace / "zero_caption.sqlite3"
    assert window.workspace.root == new_workspace
    assert window.settings_page.workspace_field.text() == str(new_workspace)
    assert window.projects_page.workspace_label.text() == str(new_workspace)
    assert window.tasks_page.task_service is window.task_service
    assert new_workspace.is_dir()
    assert old_root.exists() is False
    file_handlers = [
        handler
        for handler in logger.handlers
        if isinstance(handler, logging.FileHandler)
    ]
    assert len(file_handlers) == 1
    assert Path(file_handlers[0].baseFilename).parent == new_workspace / "logs"
    assert "旧工作区已删除" in window.settings_page.feedback_label.text()

    window.close()
    window.deleteLater()
    app.processEvents()
    for handler in tuple(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


def test_main_window_saves_selected_subtitle_edit_in_background(
    tmp_path,
    monkeypatch,
) -> None:
    """任务页保存按钮应走后台线程，并把指定译文写回仓储和 `SRT`。"""

    # arrange：在临时工作区准备一个已翻译项目，避免触碰用户真实任务数据。
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    workspace = WorkspaceManager(tmp_path / "workspace")
    workspace.ensure_structure()
    container = AppContainer(
        settings=Settings(workspace_root=workspace.root),
        workspace=workspace,
        logger=logging.getLogger("test-subtitle-edit"),
        asr_hardware_info=cpu_hardware_info(),
    )
    project = Project(
        project_id="project-window-edit",
        source_video=tmp_path / "lesson.mp4",
        source_language="en",
        target_language="zh-CN",
        workspace_dir=workspace.projects_dir / "project-window-edit",
    )
    project.mark_completed()
    container.project_repository.save(project)
    task = Task("task-window-edit", project.project_id, "translate_subtitles")
    task.mark_succeeded("翻译完成", TaskCheckpoint.TRANSLATED)
    container.task_repository.save(task)
    container.subtitle_repository.save_source_segments(
        project.project_id,
        [SubtitleSegmentDTO("segment-1", 0, 1_000, "hello", "en")],
    )
    container.subtitle_repository.save_translated_segments(
        project.project_id,
        project.target_language,
        [SubtitleSegmentDTO("segment-1", 0, 1_000, "你好", "zh-CN")],
    )
    window = container.create_main_window()

    # act：像用户一样在任务页修改文本并点击保存，然后消费 Qt 线程信号。
    window.navigation.set_current_page(1)
    window.tasks_page.subtitle_translation_editor.setPlainText("你好，课堂")
    window.tasks_page.save_translation_button.click()
    deadline = monotonic() + 3
    while window._subtitle_revision_runner is not None and monotonic() < deadline:
        app.processEvents()

    # assert：线程已结束，页面、SQLite 仓储和正式字幕文件保持一致。
    assert window._subtitle_revision_runner is None
    saved = container.subtitle_repository.get_translated_segments(
        project.project_id,
        project.target_language,
    )
    assert [segment.text for segment in saved] == ["你好，课堂"]
    assert window.tasks_page.subtitle_translation_editor.toPlainText() == "你好，课堂"
    subtitle_path = project.workspace_dir / "subtitles" / "translated-zh-CN.srt"
    assert "你好，课堂" in subtitle_path.read_text(encoding="utf-8")

    window.close()
    window.deleteLater()
    app.processEvents()
