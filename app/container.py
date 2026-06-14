"""桌面应用骨架的简单依赖容器。

容器属于 app 层，负责把具体实现装配起来再交给 UI 使用。
这样页面类就不需要自己直接创建基础设施对象。
"""

from __future__ import annotations

from dataclasses import dataclass
import logging

from config.settings import Settings
from core.services.task_service import TaskService
from infrastructure.task.job_queue import JobQueue
from ui.windows.main_window import MainWindow
from infrastructure.storage.workspace import WorkspaceManager


@dataclass(slots=True)
class AppContainer:
    """基于共享依赖创建应用服务和窗口对象。"""

    settings: Settings
    workspace: WorkspaceManager
    logger: logging.Logger

    def create_task_service(self) -> TaskService:
        """构建当前版本的任务服务实现。

        现在的服务内部还是一个基于内存队列的占位实现。
        以后如果切换成持久化队列或仓储驱动的真实实现，优先在这个工厂方法里
        替换，而不是去修改 UI 页面代码。
        """

        return TaskService(job_queue=JobQueue(), logger=self.logger)

    def create_main_window(self) -> MainWindow:
        """构建主窗口，并注入它依赖的服务。"""

        # 任务服务在这里创建一次，然后由主窗口和子页面共享。
        # 这样任务相关状态就集中保存在一个对象里，不会在多个控件之间重复拷贝。
        task_service = self.create_task_service()
        return MainWindow(
            settings=self.settings,
            workspace=self.workspace,
            task_service=task_service,
            logger=self.logger,
        )
