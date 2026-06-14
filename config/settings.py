"""应用骨架的配置加载模块。

这个文件负责把 TOML 配置数据转换成应用其他部分可直接使用的 Python 对象。
把配置解析集中放在这里，可以避免文件读取逻辑散落到 UI 和服务层里。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib


@dataclass(slots=True)
class Settings:
    """保存应用运行时使用的配置项。

    这里主要是数据，没有复杂行为，所以 dataclass 很合适。
    每个字段的默认值定义了“没有配置文件时应用如何启动”。
    """

    app_name: str = "Zero Caption"
    workspace_root: Path = Path("data")
    log_level: str = "INFO"
    language: str = "zh-CN"
    theme: str = "system"
    default_page: str = "projects"


def load_settings(path: str | Path | None = None) -> Settings:
    """从 TOML 文件中加载配置。

    参数：
        path：可选的配置文件路径。不传时，默认使用仓库中的
            `config/default.toml`。

    返回：
        一个 Settings 实例。如果文件不存在，就返回 dataclass 的默认值，
        让应用仍然可以正常启动。
    """

    settings = Settings()

    # `Path` 比手工拼接字符串更适合处理文件路径。
    # 它把“检查路径是否存在”“拼接子路径”等常见操作都封装在一个对象里。
    config_path = Path(path) if path else Path("config/default.toml")
    if not config_path.exists():
        return settings

    # `tomllib` 需要接收二进制数据，所以这里用二进制模式打开文件。
    with config_path.open("rb") as handle:
        data = tomllib.load(handle)

    # 配置文件按分组划分。
    # 某个键缺失时不应该导致启动失败，所以每个值都回退到当前默认配置。
    app = data.get("app", {})
    ui = data.get("ui", {})
    return Settings(
        app_name=app.get("name", settings.app_name),
        workspace_root=Path(app.get("workspace_root", str(settings.workspace_root))),
        log_level=app.get("log_level", settings.log_level),
        language=app.get("language", settings.language),
        theme=app.get("theme", settings.theme),
        default_page=ui.get("default_page", settings.default_page),
    )
