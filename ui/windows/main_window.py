"""主应用窗口模块。

这个文件属于界面层，负责组装控件并把用户操作连接到服务层。
它不应该直接实现媒体处理或其他重型业务逻辑。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QHBoxLayout,
    QStackedWidget,
    QMessageBox,
)

from config.paths import resource_path
from config.settings import EngineSettings, Settings, TranslationSettings
from core.dto.asr_dto import AsrHardwareInfoDTO
from core.domain.enums import ExportMode, ProcessingMode
from core.dto.pipeline_dto import ProcessVideoResult
from core.dto.subtitle_dto import (
    EditSubtitleTranslationInput,
    RetranslateSubtitleInput,
    SubtitleTranslationUpdateResult,
    TranslationProgressDTO,
)
from core.services.task_service import TaskService
from core.dto.task_dto import ExportVideoResult, ReexportProjectInput
from infrastructure.storage.workspace import WorkspaceManager
from infrastructure.task.progress_bus import ProgressBus
from ui.dialogs.import_dialog import ImportDialog
from ui.pages.projects_page import ProjectsPage
from ui.pages.settings_page import SettingsPage
from ui.pages.tasks_page import TasksPage
from ui.widgets.navigation import NavigationWidget
from ui.widgets.status_bar import StatusBarWidget
from ui.viewmodels.pipeline_runner import PipelineRunner
from ui.viewmodels.subtitle_revision_runner import SubtitleRevisionRunner
from ui.viewmodels.translation_test_runner import TranslationTestRunner


class MainWindow(QMainWindow):
    """承载导航、页面和状态栏的顶层窗口。"""

    def __init__(
        self,
        settings: Settings,
        workspace: WorkspaceManager,
        task_service: TaskService,
        task_service_factory: Callable[[], TaskService],
        settings_updater: Callable[[EngineSettings], Settings],
        workspace_updater: Callable[[Path], Settings],
        workspace_deleter: Callable[[Path], None],
        translation_model_tester: Callable[[TranslationSettings, str], str],
        asr_hardware_info: AsrHardwareInfoDTO,
        logger: logging.Logger,
        progress_bus: ProgressBus,
    ) -> None:
        """创建主窗口，并把子控件之间的关系连接起来。"""

        super().__init__()
        self.settings = settings
        self.workspace = workspace
        self.task_service = task_service
        self.task_service_factory = task_service_factory
        self.settings_updater = settings_updater
        self.workspace_updater = workspace_updater
        self.workspace_deleter = workspace_deleter
        self.translation_model_tester = translation_model_tester
        self.asr_hardware_info = asr_hardware_info
        self.logger = logger
        self.progress_bus = progress_bus
        # 每个视频流程拥有独立 `QThread` 和 `TaskService`，避免不同任务
        # 共享识别引擎实例。字典保留线程对象，防止 Qt 在线程结束前回收它。
        self._pipeline_runners: dict[int, PipelineRunner] = {}
        self._pipeline_project_ids: dict[int, str | None] = {}
        self._pipeline_task_services: dict[int, TaskService] = {}
        # 运行中的项目可能暂时占用音频或视频文件。第一次删除会立即尝试，
        # 同时保留项目目录，在线程退出后再次执行幂等清理，避免残留文件夹。
        self._pending_task_deletions: dict[str, str] = {}
        self._max_pipeline_concurrency = settings.task.max_concurrency
        self._translation_test_runner: TranslationTestRunner | None = None
        self._subtitle_revision_runner: SubtitleRevisionRunner | None = None
        # 同一张品牌图同时用于窗口图标和页眉，避免源码运行与安装版出现两套视觉标识。
        # `resource_path` 会自动兼容仓库路径和 `PyInstaller` 的临时资源目录。
        logo_path = resource_path("resources/icons/zero-caption-logo.png")
        self.setWindowIcon(QIcon(str(logo_path)))
        self.setWindowTitle(settings.app_name)
        self.resize(1200, 800)

        # 这些控件都会随着主窗口长期存在，并由整个窗口共享。
        self.navigation = NavigationWidget()
        self.stack = QStackedWidget()
        self.projects_page = ProjectsPage(workspace=workspace, task_service=task_service)
        self.tasks_page = TasksPage(task_service=task_service)
        self.tasks_page.set_project_operation_capacity(
            active_count=0,
            max_concurrency=self._max_pipeline_concurrency,
        )
        self.settings_page = SettingsPage(
            settings=settings,
            asr_hardware_info=asr_hardware_info,
        )
        self.status_widget = StatusBarWidget(task_service=task_service)
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(100)
        self._progress_timer.timeout.connect(self._drain_progress_events)
        self._progress_timer.start()

        # `QStackedWidget` 一次只显示一个页面，但会把其他页面对象也保留在内存里。
        # 对这种小型桌面工具来说，这是一个足够简单直接的页面切换方案。
        self.stack.addWidget(self.projects_page)
        self.stack.addWidget(self.tasks_page)
        self.stack.addWidget(self.settings_page)

        # 界面框架里的信号机制是内建事件机制。
        # 这里导航控件发出页面索引，页面栈据此切换到对应页。
        self.navigation.page_changed.connect(self.stack.setCurrentIndex)
        self.settings_page.save_requested.connect(
            self._handle_engine_settings_save
        )
        self.settings_page.workspace_change_requested.connect(
            self._handle_workspace_change
        )
        self.settings_page.test_requested.connect(
            self._handle_translation_test_requested
        )
        self.tasks_page.create_requested.connect(self.open_import_dialog)
        self.tasks_page.delete_requested.connect(
            self._handle_delete_requested
        )
        self.tasks_page.retry_requested.connect(
            self._handle_retry_requested
        )
        self.tasks_page.reexport_requested.connect(
            self._handle_reexport_requested
        )
        self.tasks_page.save_translation_requested.connect(
            self._handle_subtitle_edit_requested
        )
        self.tasks_page.retranslate_requested.connect(
            self._handle_subtitle_retranslation_requested
        )
        self.tasks_page.refresh_history()

        root = QWidget()
        layout = QVBoxLayout(root)

        # 顶部区域放全局操作，这些按钮不应该随着页面切换而消失。
        header = QHBoxLayout()
        self.brand_logo = QLabel()
        self.brand_logo.setObjectName("brandLogo")
        self.brand_logo.setPixmap(self.windowIcon().pixmap(36, 36))
        self.brand_logo.setToolTip("Zero Caption")
        title = QLabel("Zero Caption")
        self.import_button = QPushButton("创建视频任务")
        self.import_button.setObjectName("createVideoTaskHeaderButton")
        self.import_button.clicked.connect(self.open_import_dialog)
        header.addWidget(self.brand_logo)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.import_button)

        layout.addLayout(header)
        layout.addWidget(self.navigation)
        layout.addWidget(self.stack, 1)
        layout.addWidget(self.status_widget)
        self.setCentralWidget(root)

    def open_import_dialog(self) -> None:
        """收集参数并把完整处理请求提交到后台线程。"""

        if not self._has_pipeline_capacity():
            QMessageBox.information(
                self,
                "后台任务已满",
                f"当前最多同时处理 {self._max_pipeline_concurrency} 个视频，"
                "请等待其中一个任务完成。",
            )
            return

        dialog = ImportDialog(
            self,
            default_source_language=self.settings.subtitle.source_language,
            default_target_language=self.settings.subtitle.target_language,
            translation_configured=(
                self.settings.engine.translation.is_configured()
            ),
            asr_runtime_summary=self._asr_runtime_summary(),
            default_output_directory=self.workspace.exports_dir,
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return

        request = dialog.to_request(self.workspace.root)
        # 每个视频流程使用新装配的服务实例。仓储、进度总线和高资源调度器
        # 仍由容器共享，识别引擎与翻译客户端则不会跨线程复用。
        task_service = self.task_service_factory()
        # 创建完成后停留在任务工作区，让用户立即看到视频条目、当前阶段
        # 和逐句译文，而不是在任务运行期间反复切换页面寻找反馈。
        self.navigation.set_current_page(1)
        if not self._pipeline_runners:
            self.tasks_page.show_running()
        self._start_project_operation(
            operation=lambda: task_service.process_video(request),
            success_handler=self._handle_pipeline_success,
            message="正在创建并处理视频任务……",
            task_service=task_service,
        )

    def _handle_retry_requested(
        self,
        project_id: str,
        processing_mode_value: str,
    ) -> None:
        """在后台继续失败或应用重启后待恢复的已有项目。"""

        processing_mode = ProcessingMode(processing_mode_value)
        if (
            processing_mode is ProcessingMode.FULL_PIPELINE
            and not self.settings.engine.translation.is_configured()
        ):
            self.tasks_page.set_project_operation_capacity(
                active_count=len(self._pipeline_runners),
                max_concurrency=self._max_pipeline_concurrency,
                message="完整流程恢复前，请先在设置页保存可用的大模型配置。",
                active_project_ids=self._active_pipeline_project_ids(),
            )
            return
        task_service = self.task_service_factory()
        self._start_project_operation(
            operation=lambda: task_service.retry_video(project_id),
            success_handler=self._handle_pipeline_success,
            message="正在从已有检查点继续处理……",
            project_id=project_id,
            task_service=task_service,
        )

    def _handle_reexport_requested(
        self,
        project_id: str,
        export_mode_value: str,
        output_path_value: str,
    ) -> None:
        """在后台使用当前字幕、模式和用户选择的路径重新导出成品。"""

        request = ReexportProjectInput(
            project_id=project_id,
            mode=ExportMode(export_mode_value),
            output_path=Path(output_path_value),
        )
        task_service = self.task_service_factory()
        self._start_project_operation(
            operation=lambda: task_service.reexport_project(request),
            success_handler=self._handle_reexport_success,
            message="正在使用当前字幕重新导出成品……",
            project_id=project_id,
            task_service=task_service,
        )

    def _handle_delete_requested(
        self,
        project_id: str,
        workspace_dir: str,
    ) -> None:
        """删除任意状态的任务，并为运行中项目登记退出后收尾。"""

        active = project_id in self._active_pipeline_project_ids()
        revision_project_id = self._active_revision_project_id()
        needs_final_cleanup = active or revision_project_id == project_id
        if needs_final_cleanup:
            self._pending_task_deletions[project_id] = workspace_dir

        try:
            self.task_service.delete_video_task(project_id, workspace_dir)
        except (OSError, RuntimeError, ValueError) as exc:
            if needs_final_cleanup:
                # Windows 可能暂时锁住正在读写的音视频文件。保留待删除记录，
                # 后台线程结束时会自动重试，不要求用户再次点击按钮。
                message = f"任务正在退出，项目将在后台操作结束后删除：{exc}"
                self.status_widget.show_message(message)
                self.tasks_page.message_label.setText(message)
                return
            self.logger.exception("删除视频任务失败")
            QMessageBox.warning(self, "删除失败", str(exc))
            self.status_widget.show_message(f"删除任务失败：{exc}")
            return

        self.tasks_page.refresh_history()
        if needs_final_cleanup:
            message = "任务已从列表移除，后台操作退出后会再次检查项目目录。"
        else:
            self._pending_task_deletions.pop(project_id, None)
            message = "任务记录和项目目录已删除。"
        self.status_widget.show_message(message)

    def _start_project_operation(
        self,
        operation: Callable[[], object],
        success_handler: Callable[[object], None],
        message: str,
        project_id: str | None = None,
        task_service: TaskService | None = None,
    ) -> bool:
        """启动一个视频级后台操作，并返回是否成功占用普通并发槽位。"""

        if project_id and project_id in self._active_pipeline_project_ids():
            self.tasks_page.set_project_operation_capacity(
                active_count=len(self._pipeline_runners),
                max_concurrency=self._max_pipeline_concurrency,
                message="这个视频已有后台操作正在执行，请勿重复提交。",
                active_project_ids=self._active_pipeline_project_ids(),
            )
            return False
        if not self._has_pipeline_capacity():
            QMessageBox.information(
                self,
                "后台任务已满",
                f"当前最多同时处理 {self._max_pipeline_concurrency} 个视频。",
            )
            return False
        self.navigation.set_current_page(1)
        runner = PipelineRunner(operation)
        runner.succeeded.connect(success_handler)
        runner.failed.connect(
            lambda failure, runner=runner: self._handle_pipeline_failure(
                failure,
                runner,
            )
        )
        runner.finished.connect(
            lambda runner=runner: self._release_pipeline_runner(runner)
        )
        runner_id = id(runner)
        self._pipeline_runners[runner_id] = runner
        self._pipeline_project_ids[runner_id] = project_id
        if task_service is not None:
            self._pipeline_task_services[runner_id] = task_service
        self._sync_pipeline_capacity(message)
        runner.start()
        return True

    def _drain_progress_events(self) -> None:
        """在 UI 线程消费后台任务事件并刷新任务页和状态栏。"""

        for summary in self.progress_bus.drain():
            if isinstance(summary, TranslationProgressDTO):
                self.tasks_page.update_translation_progress(summary)
                continue
            self.tasks_page.update_summary(summary)
            self.status_widget.update_summary(summary)

    def _handle_pipeline_success(self, result: ProcessVideoResult) -> None:
        """处理后台线程成功信号，刷新项目页并展示本次主要产物。"""

        project_id = result.project.project.project_id
        if project_id in self._pending_task_deletions:
            self.status_widget.show_message("后台任务已退出，正在完成项目删除。")
            return

        self.projects_page.show_result(result)
        self.tasks_page.refresh_history()
        self.navigation.set_current_page(1)
        if result.export is not None:
            output_path = result.export.export_record.output_path
            self.status_widget.show_message(f"处理完成：{output_path}")
            return

        subtitle_path = result.subtitle_path
        self.status_widget.show_message(f"原文字幕生成完成：{subtitle_path}")

    def _handle_pipeline_failure(
        self,
        message: str,
        runner: PipelineRunner | None = None,
    ) -> None:
        """处理后台线程失败信号，并把错误展示给用户。"""

        project_id = None
        if runner is not None:
            runner_id = id(runner)
            project_id = self._pipeline_project_ids.get(runner_id)
            if not project_id:
                service = self._pipeline_task_services.get(runner_id)
                project_id = service.current_project_id() if service else None
        if project_id and project_id in self._pending_task_deletions:
            self.tasks_page.refresh_history()
            self.status_widget.show_message("后台任务已退出，正在完成项目删除。")
            return

        self.tasks_page.refresh_history()
        self.status_widget.show_message(f"处理失败：{message}")
        QMessageBox.critical(self, "处理失败", message)

    def _handle_reexport_success(self, result: ExportVideoResult) -> None:
        """刷新项目历史，并展示重新导出的最新文件路径。"""

        if result.project.project_id in self._pending_task_deletions:
            self.status_widget.show_message("后台导出已退出，正在完成项目删除。")
            return

        self.tasks_page.refresh_history()
        output_path = result.export_record.output_path
        self.status_widget.show_message(f"重新导出完成：{output_path}")

    def _release_pipeline_runner(self, runner: PipelineRunner) -> None:
        """释放指定已结束线程，并立即开放一个普通任务并发槽位。"""

        stored_runner = self._pipeline_runners.pop(id(runner), None)
        if stored_runner is None:
            return
        self._pipeline_project_ids.pop(id(runner), None)
        self._pipeline_task_services.pop(id(runner), None)
        stored_runner.deleteLater()
        self._sync_pipeline_capacity()
        self.tasks_page.refresh_history()
        self._flush_pending_task_deletions()

    def _has_pipeline_capacity(self) -> bool:
        """判断当前是否还能提交一个视频级后台流程。"""

        return len(self._pipeline_runners) < self._max_pipeline_concurrency

    def _active_pipeline_project_ids(self) -> set[str]:
        """返回正在恢复或重新导出的已有项目编号集合。"""

        # 新建流程启动时尚未生成项目编号。每个后台线程持有独立服务实例，
        # 创建项目用例结束后即可从该实例读取准确编号，不需要按事件顺序猜测。
        for runner_id, service in list(self._pipeline_task_services.items()):
            if self._pipeline_project_ids.get(runner_id):
                continue
            project_id = service.current_project_id()
            if project_id:
                self._pipeline_project_ids[runner_id] = project_id

        return {
            project_id
            for project_id in self._pipeline_project_ids.values()
            if project_id
        }

    def _sync_pipeline_capacity(self, message: str = "") -> None:
        """把后台线程数量同步到任务页和窗口顶部创建按钮。"""

        active_count = len(self._pipeline_runners)
        self.tasks_page.set_project_operation_capacity(
            active_count=active_count,
            max_concurrency=self._max_pipeline_concurrency,
            message=message,
            active_project_ids=self._active_pipeline_project_ids(),
        )
        self.import_button.setEnabled(self._has_pipeline_capacity())

    def _handle_engine_settings_save(self, value: object) -> None:
        """保存识别与翻译配置，并重建后续任务使用的服务。"""

        if not isinstance(value, EngineSettings):
            self.settings_page.show_save_result(False, "设置数据格式不正确。")
            return

        try:
            # 第一步：由 `app` 层回调负责写入用户配置并更新容器状态。
            updated_settings = self.settings_updater(value)

            # 第二步：重新装配任务服务。已经运行的后台任务仍持有旧服务，
            # 新服务只影响用户随后发起的任务，不会中途替换正在执行的适配器。
            task_service = self.task_service_factory()
        except (OSError, RuntimeError, ValueError) as exc:
            # 日志只记录异常类型和路径类信息，配置对象及 API 密钥不会进入日志。
            self.logger.exception("保存识别与大模型设置失败")
            self.settings_page.show_save_result(False, f"保存失败：{exc}")
            return

        self.settings = updated_settings
        self.task_service = task_service
        self.tasks_page.set_task_service(task_service)
        self._sync_pipeline_capacity()
        self.settings_page.apply_saved_engine_settings(updated_settings.engine)
        message = "引擎设置已自动保存，后续任务将使用新配置。"
        self.settings_page.show_save_result(True, message)
        self.status_widget.show_message(message)

    def _handle_workspace_change(self, value: object) -> None:
        """切换本地工作区，并在成功后询问是否删除旧目录。"""

        if not isinstance(value, Path):
            self.settings_page.show_save_result(False, "工作区路径格式不正确。")
            return
        if self._pipeline_runners or (
            self._subtitle_revision_runner is not None
            and self._subtitle_revision_runner.isRunning()
        ):
            self.settings_page.show_save_result(
                False,
                "视频任务或字幕修改正在运行，请完成后再切换工作区。",
            )
            return

        previous_root = self.workspace.root.expanduser().resolve()
        requested_root = value.expanduser().resolve()
        workspace_changed = requested_root != previous_root

        try:
            # 第一步：容器先创建新目录、初始化数据库并持久化路径。
            updated_settings = self.workspace_updater(requested_root)

            # 第二步：路径变化后重建服务，让历史列表和后续任务立即读取新数据库。
            task_service = (
                self.task_service_factory()
                if workspace_changed
                else self.task_service
            )
        except (OSError, RuntimeError, ValueError) as exc:
            self.logger.exception("切换本地工作区失败")
            self.settings_page.show_save_result(False, f"工作区切换失败：{exc}")
            return

        self.settings = updated_settings
        self.task_service = task_service
        self.tasks_page.set_task_service(task_service)
        self.tasks_page.refresh_history()
        self.projects_page.show_workspace_root(updated_settings.workspace_root)
        self.settings_page.apply_saved_workspace(updated_settings.workspace_root)

        message = f"工作区已切换为：{updated_settings.workspace_root}"
        self.settings_page.show_save_result(True, message)
        self.status_widget.show_message(message)

        if not workspace_changed:
            return

        # 第三步：新工作区已经生效后再询问旧目录，默认选择“否”。
        # 这样即使用户选择删除，后续失败也不会让应用失去可用工作区。
        answer = QMessageBox.question(
            self,
            "是否删除旧工作区",
            "新工作区已生效，旧数据不会自动迁移。\n\n"
            "是否永久删除旧工作区中的项目、字幕、缓存、日志和数据库？\n\n"
            f"旧工作区：{previous_root}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            self.workspace_deleter(previous_root)
        except (OSError, RuntimeError, ValueError) as exc:
            self.logger.exception("删除旧工作区失败")
            message = f"新工作区已生效，但旧工作区删除失败：{exc}"
            self.settings_page.show_save_result(False, message)
            self.status_widget.show_message(message)
            return

        message = f"工作区已切换，旧工作区已删除：{previous_root}"
        self.settings_page.show_save_result(True, message)
        self.status_widget.show_message(message)

    def _handle_translation_test_requested(
        self,
        value: object,
        user_prompt: str,
    ) -> None:
        """把当前表单快照交给后台线程测试，避免网络请求阻塞界面。"""

        if not isinstance(value, TranslationSettings):
            self.settings_page.show_test_result(False, "测试配置格式不正确。")
            return
        if (
            self._translation_test_runner is not None
            and self._translation_test_runner.isRunning()
        ):
            self.settings_page.show_test_result(False, "已有模型测试正在进行。")
            return

        self._translation_test_runner = TranslationTestRunner(
            tester=self.translation_model_tester,
            settings=value,
            user_prompt=user_prompt,
        )
        self._translation_test_runner.succeeded.connect(
            self._handle_translation_test_success
        )
        self._translation_test_runner.failed.connect(
            self._handle_translation_test_failure
        )
        self._translation_test_runner.finished.connect(
            self._release_translation_test_runner
        )
        self._translation_test_runner.start()

    def _handle_translation_test_success(self, result: str) -> None:
        """显示模型测试返回，并恢复测试按钮。"""

        self.settings_page.show_test_result(True, result)
        self.status_widget.show_message("大模型测试成功。")

    def _handle_translation_test_failure(self, message: str) -> None:
        """在设置页展示模型测试错误，不弹出阻塞式对话框。"""

        self.settings_page.show_test_result(False, f"测试失败：{message}")
        self.status_widget.show_message("大模型测试失败。")

    def _release_translation_test_runner(self) -> None:
        """在线程结束后释放引用，允许用户再次测试。"""

        if (
            self._translation_test_runner is not None
            and not self._translation_test_runner.isRunning()
        ):
            self._translation_test_runner.deleteLater()
            self._translation_test_runner = None

    def _handle_subtitle_edit_requested(
        self,
        project_id: str,
        segment_id: str,
        translated_text: str,
    ) -> None:
        """把用户手工编辑提交给统一的字幕修订后台线程。"""

        self._start_subtitle_revision(
            EditSubtitleTranslationInput(
                project_id=project_id,
                segment_id=segment_id,
                translated_text=translated_text,
            ),
            "正在保存当前译文……",
        )

    def _handle_subtitle_retranslation_requested(
        self,
        project_id: str,
        segment_id: str,
    ) -> None:
        """使用当前大模型配置在后台重新翻译选中的一条字幕。"""

        if not self.settings.engine.translation.is_configured():
            self.tasks_page.show_subtitle_update_error(
                "重新翻译前，请先在设置页填写可用的大模型配置。"
            )
            return
        self._start_subtitle_revision(
            RetranslateSubtitleInput(
                project_id=project_id,
                segment_id=segment_id,
            ),
            "正在调用大模型重新翻译这一条……",
        )

    def _start_subtitle_revision(
        self,
        request: EditSubtitleTranslationInput | RetranslateSubtitleInput,
        message: str,
    ) -> None:
        """校验并启动单条字幕修订，避免与完整视频流程并发写入。"""

        if self._pipeline_runners:
            self.tasks_page.show_subtitle_update_error(
                "视频任务运行期间不能修改字幕，请等待后台任务完成。"
            )
            return
        if (
            self._subtitle_revision_runner is not None
            and self._subtitle_revision_runner.isRunning()
        ):
            self.tasks_page.show_subtitle_update_error(
                "已有一条字幕正在保存或重新翻译。"
            )
            return

        self.tasks_page.set_subtitle_action_running(True, message)
        self._subtitle_revision_runner = SubtitleRevisionRunner(
            task_service=self.task_service,
            request=request,
        )
        self._subtitle_revision_runner.succeeded.connect(
            self._handle_subtitle_revision_success
        )
        self._subtitle_revision_runner.failed.connect(
            self._handle_subtitle_revision_failure
        )
        self._subtitle_revision_runner.finished.connect(
            self._release_subtitle_revision_runner
        )
        self._subtitle_revision_runner.start()

    def _handle_subtitle_revision_success(
        self,
        result: SubtitleTranslationUpdateResult,
    ) -> None:
        """刷新持久化任务和选中字幕，并提示成品视频不会自动更新。"""

        if result.project_id in self._pending_task_deletions:
            self.status_widget.show_message("字幕操作已退出，正在完成项目删除。")
            return

        self.tasks_page.refresh_history(select_project_id=result.project_id)
        message = (
            f"第 {result.item.current_index} 条译文已更新："
            f"{result.subtitle_path}。已导出的视频不会自动改变。"
        )
        self.tasks_page.show_subtitle_update_result(result.item, message)
        self.status_widget.show_message(
            f"第 {result.item.current_index} 条字幕译文已更新。"
        )

    def _handle_subtitle_revision_failure(self, message: str) -> None:
        """在任务页保留当前编辑文本并展示后台修订错误。"""

        project_id = self._active_revision_project_id()
        if project_id and project_id in self._pending_task_deletions:
            self.status_widget.show_message("字幕操作已退出，正在完成项目删除。")
            return

        self.tasks_page.show_subtitle_update_error(f"字幕更新失败：{message}")
        self.status_widget.show_message("字幕更新失败。")

    def _release_subtitle_revision_runner(self) -> None:
        """释放已结束的单句修订线程，允许继续处理其他字幕。"""

        if (
            self._subtitle_revision_runner is not None
            and not self._subtitle_revision_runner.isRunning()
        ):
            self._subtitle_revision_runner.deleteLater()
            self._subtitle_revision_runner = None
            self._flush_pending_task_deletions()

    def _active_revision_project_id(self) -> str | None:
        """返回当前单句修订线程关联的项目编号。"""

        runner = self._subtitle_revision_runner
        if runner is None or not runner.isRunning():
            return None
        return runner.request.project_id

    def _flush_pending_task_deletions(self) -> None:
        """在线程退出后重试项目删除，清理由文件锁造成的残留。"""

        active_project_ids = self._active_pipeline_project_ids()
        revision_project_id = self._active_revision_project_id()
        removed_any = False
        for project_id, workspace_dir in list(
            self._pending_task_deletions.items()
        ):
            if project_id in active_project_ids or project_id == revision_project_id:
                continue
            try:
                self.task_service.delete_video_task(project_id, workspace_dir)
            except (OSError, RuntimeError, ValueError) as exc:
                self.logger.exception("后台任务退出后清理项目失败")
                self.status_widget.show_message(f"项目目录清理失败：{exc}")
                continue
            self._pending_task_deletions.pop(project_id, None)
            removed_any = True

        if removed_any:
            self.tasks_page.refresh_history()
            self.status_widget.show_message("任务记录和项目目录已删除。")

    def _asr_runtime_summary(self) -> str:
        """生成创建任务对话框使用的本次识别运行参数摘要。"""

        asr_settings = self.settings.engine.asr
        hardware = self.asr_hardware_info
        model_name = (
            hardware.recommended_model
            if asr_settings.model_name == "auto"
            else asr_settings.model_name
        )
        device = (
            hardware.recommended_device
            if asr_settings.device == "auto"
            else asr_settings.device
        )
        compute_type = (
            hardware.recommended_compute_type
            if asr_settings.compute_type == "auto" and device == "cuda"
            else (
                "int8"
                if asr_settings.compute_type == "auto"
                else asr_settings.compute_type
            )
        )
        device_label = "GPU" if device == "cuda" else "CPU"
        return f"{model_name} / {device_label} / {compute_type}"
