"""主应用窗口模块。

这个文件属于界面层，负责组装控件并把用户操作连接到服务层。
它不应该直接实现媒体处理或其他重型业务逻辑。
"""

from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import QTimer
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

from config.settings import EngineSettings, Settings, TranslationSettings
from core.dto.asr_dto import AsrHardwareInfoDTO
from core.dto.pipeline_dto import ProcessVideoResult
from core.dto.subtitle_dto import TranslationProgressDTO
from core.services.task_service import TaskService
from infrastructure.storage.workspace import WorkspaceManager
from infrastructure.task.progress_bus import ProgressBus
from ui.dialogs.import_dialog import ImportDialog
from ui.pages.projects_page import ProjectsPage
from ui.pages.settings_page import SettingsPage
from ui.pages.tasks_page import TasksPage
from ui.widgets.navigation import NavigationWidget
from ui.widgets.status_bar import StatusBarWidget
from ui.viewmodels.pipeline_runner import PipelineRunner
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
        self.translation_model_tester = translation_model_tester
        self.logger = logger
        self.progress_bus = progress_bus
        self._pipeline_runner: PipelineRunner | None = None
        self._translation_test_runner: TranslationTestRunner | None = None
        self.setWindowTitle(settings.app_name)
        self.resize(1200, 800)

        # 这些控件都会随着主窗口长期存在，并由整个窗口共享。
        self.navigation = NavigationWidget()
        self.stack = QStackedWidget()
        self.projects_page = ProjectsPage(workspace=workspace, task_service=task_service)
        self.tasks_page = TasksPage(task_service=task_service)
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
        self.settings_page.test_requested.connect(
            self._handle_translation_test_requested
        )

        root = QWidget()
        layout = QVBoxLayout(root)

        # 顶部区域放全局操作，这些按钮不应该随着页面切换而消失。
        header = QHBoxLayout()
        title = QLabel("Zero Caption")
        import_button = QPushButton("导入视频")
        import_button.clicked.connect(self.open_import_dialog)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(import_button)

        layout.addLayout(header)
        layout.addWidget(self.navigation)
        layout.addWidget(self.stack, 1)
        layout.addWidget(self.status_widget)
        self.setCentralWidget(root)

    def open_import_dialog(self) -> None:
        """收集参数并把完整处理请求提交到后台线程。"""

        if self._pipeline_runner is not None and self._pipeline_runner.isRunning():
            QMessageBox.information(self, "任务进行中", "请等待当前视频处理任务完成。")
            return

        dialog = ImportDialog(
            self,
            default_source_language=self.settings.subtitle.source_language,
            default_target_language=self.settings.subtitle.target_language,
            translation_configured=(
                self.settings.engine.translation.is_configured()
            ),
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return

        request = dialog.to_request(self.workspace.root)
        self.tasks_page.show_running()
        self._pipeline_runner = PipelineRunner(self.task_service, request)
        self._pipeline_runner.succeeded.connect(self._handle_pipeline_success)
        self._pipeline_runner.failed.connect(self._handle_pipeline_failure)
        self._pipeline_runner.finished.connect(self._release_pipeline_runner)
        self._pipeline_runner.start()

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

        self.projects_page.show_result(result)
        self.navigation.page_changed.emit(0)
        if result.export is not None:
            output_path = result.export.export_record.output_path
            self.status_widget.show_message(f"处理完成：{output_path}")
            return

        subtitle_path = result.subtitle_path
        self.status_widget.show_message(f"原文字幕生成完成：{subtitle_path}")

    def _handle_pipeline_failure(self, message: str) -> None:
        """处理后台线程失败信号，并把错误展示给用户。"""

        self.status_widget.show_message(f"处理失败：{message}")
        QMessageBox.critical(self, "处理失败", message)

    def _release_pipeline_runner(self) -> None:
        """在线程结束后释放引用，允许用户提交下一次任务。"""

        if self._pipeline_runner is not None and not self._pipeline_runner.isRunning():
            self._pipeline_runner.deleteLater()
            self._pipeline_runner = None

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
        self.settings_page.apply_saved_engine_settings(updated_settings.engine)
        message = "引擎设置已保存，后续任务将使用新配置。"
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
