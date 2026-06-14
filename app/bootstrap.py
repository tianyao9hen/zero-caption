"""应用启动装配辅助模块。

这个文件属于 app 层，负责组装配置、工作区、日志和依赖容器等共享运行对象。
真正的业务流程编排不应该写在这里。
"""

from __future__ import annotations

from dataclasses import dataclass

from config.settings import Settings, load_settings
from infrastructure.logging.setup import configure_logging
from infrastructure.storage.workspace import WorkspaceManager
from app.container import AppContainer


@dataclass(slots=True)
class ApplicationContext:
    """打包应用启动后会长期存在的共享对象。

    dataclass 适合这种以保存数据为主的小型状态对象，能减少样板代码。
    `slots=True` 可以限制实例属性集合，降低因为属性名写错而偷偷新增属性
    的风险，这对初学者尤其有帮助。
    """

    settings: Settings
    workspace: WorkspaceManager
    container: AppContainer


def bootstrap_application() -> ApplicationContext:
    """创建并连接桌面应用所需的共享对象。"""

    # 第一步：从磁盘读取配置。
    # 如果是第一次打开仓库，还没有配置文件，就回退到默认值。
    settings = load_settings()

    # 第二步：创建工作区管理器，并提前确保目录结构存在。
    # 这样后面的组件在写日志或保存数据时，不会因为目录缺失而失败。
    workspace = WorkspaceManager(settings.workspace_root)
    workspace.ensure_structure()

    # 第三步：尽早初始化日志。
    # 这样后续服务如果在启动阶段报错，至少能留下文件日志，而不是静默失败。
    logger = configure_logging(workspace.logs_dir, settings.log_level)

    # 第四步：创建依赖容器。
    # 界面层通过容器拿到已经装配好的服务，而不是自己在页面里到处实例化对象。
    container = AppContainer(settings=settings, workspace=workspace, logger=logger)
    return ApplicationContext(settings=settings, workspace=workspace, container=container)
