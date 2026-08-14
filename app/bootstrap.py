"""应用启动装配辅助模块。

这个文件属于 `app` 层，负责把配置、工作区、日志和依赖容器组装成桌面应用
启动所需的共享对象。这里不编排业务流程，只负责启动期装配。
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from pathlib import Path

from app.container import AppContainer
from config.settings import Settings, load_settings
from config.paths import resource_path, user_data_path
from infrastructure.logging.setup import configure_logging
from infrastructure.storage.workspace import WorkspaceManager
from scripts.check_runtime import RuntimeReport, probe_runtime


@dataclass(slots=True)
class ApplicationContext:
    """打包应用启动后会长期共享的对象。

    这个对象把启动期构建出的配置、工作区和依赖容器集中到一起，
    方便入口文件和后续界面层统一使用。
    """

    settings: Settings
    workspace: WorkspaceManager
    container: AppContainer


def build_runtime_report(settings: Settings) -> RuntimeReport:
    """构建当前运行环境的探针结果。

    这里先提供一个纯函数入口，后续设置页、状态栏或启动诊断都可以复用，
    避免在多个层里重复实现依赖检查逻辑。
    """

    return probe_runtime(settings=settings, workspace_root=settings.workspace_root)


def _resolve_runtime_settings(settings: Settings) -> Settings:
    """把可写数据与只读依赖分别解析到正确的运行时目录。"""

    # 安装目录通常位于 `Program Files`，普通用户没有权限在其中写入项目数据。
    # 因此只有绝对路径才保持原样，相对路径统一迁移到用户数据根目录。
    workspace_root = user_data_path(settings.workspace_root)
    model_cache_dir = user_data_path(settings.runtime.model_cache_dir)
    ffmpeg_path = _resolve_bundled_executable(settings.runtime.ffmpeg_path)
    ffprobe_path = _resolve_bundled_executable(settings.runtime.ffprobe_path)
    return replace(
        settings,
        workspace_root=workspace_root,
        runtime=replace(
            settings.runtime,
            ffmpeg_path=ffmpeg_path,
            ffprobe_path=ffprobe_path,
            model_cache_dir=model_cache_dir,
        ),
    )


def _resolve_bundled_executable(value: str) -> str:
    """优先返回随程序发布的可执行文件，同时保留开发环境的命令回退。"""

    configured = Path(value)
    if configured.is_absolute():
        return str(configured)
    bundled = resource_path(configured)
    return str(bundled) if bundled.exists() else value


def bootstrap_application() -> ApplicationContext:
    """创建并连接桌面应用启动所需的共享对象。"""

    # 第一步：从磁盘读取配置。
    # 如果是第一次打开仓库，或者用户还没有自定义配置文件，
    # 这里会自动回退到 `Settings` 中定义的默认值。
    settings = _resolve_runtime_settings(load_settings())

    # 第二步：创建工作区管理器，并提前确保目录结构存在。
    # 这样后面的日志和数据写入不会因为目录缺失而在启动阶段失败。
    workspace = WorkspaceManager(settings.workspace_root)
    workspace.ensure_structure()

    # 第三步：尽早初始化应用级日志。
    # 启动期如果后续装配出现异常，至少还能把错误写入日志文件。
    logger = configure_logging(workspace.logs_dir, settings.log_level)

    # 第四步：创建依赖容器。
    # 这里继续保持“由容器装配具体实现，界面层只拿结果使用”的边界。
    container = AppContainer(settings=settings, workspace=workspace, logger=logger)
    return ApplicationContext(settings=settings, workspace=workspace, container=container)
