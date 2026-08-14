"""桌面应用骨架的简单依赖容器。

容器属于 app 层，负责把具体实现装配起来再交给 UI 使用。
这样页面类就不需要自己直接创建基础设施对象。
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING

from config.settings import Settings
from core.ports.asr import AsrEngine
from core.services.task_service import TaskService
from infrastructure.asr import FasterWhisperEngine
from infrastructure.storage.workspace import WorkspaceManager

if TYPE_CHECKING:
    from ui.windows.main_window import MainWindow


@dataclass(slots=True)
class AppContainer:
    """基于共享依赖创建应用服务和窗口对象。"""

    settings: Settings
    workspace: WorkspaceManager
    logger: logging.Logger

    def create_asr_engine(self) -> AsrEngine:
        """按照当前配置装配本地 ASR 适配器。

        这里属于 app 层的依赖装配职责，所以负责把配置对象中的模型名、
        设备和缓存目录翻译成具体适配器构造参数。
        真正的识别细节仍然留在 infrastructure 层。
        """

        asr_settings = self.settings.engine.asr
        return FasterWhisperEngine(
            model_name=asr_settings.model_name,
            device=asr_settings.device,
            compute_type=asr_settings.compute_type,
            model_cache_dir=self.settings.runtime.model_cache_dir,
        )

    def create_task_service(self) -> TaskService:
        """构建当前版本的任务服务实现。

        阶段 1 已经把任务编排入口定型，但启动骨架仍然先返回一个
        没有装配用例的服务对象。这样 UI 先能正常启动，
        后续再在这里接入真实仓储和用例实例。
        """

        return TaskService()

    def create_main_window(self) -> MainWindow:
        """构建主窗口，并注入它依赖的服务。"""

        from ui.windows.main_window import MainWindow

        # 任务服务在这里创建一次，然后由主窗口和子页面共享。
        # 这样任务相关状态就集中保存在一个对象里，不会在多个控件之间重复拷贝。
        task_service = self.create_task_service()
        return MainWindow(
            settings=self.settings,
            workspace=self.workspace,
            task_service=task_service,
            logger=self.logger,
        )
