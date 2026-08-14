"""应用资源路径和用户数据路径。

这个模块属于配置层，负责区分“随程序安装的只读资源”和“用户可写的数据”。
打包后的程序不能假设当前工作目录可写，因此项目、日志、SQLite 和模型缓存
都应落到用户数据目录；FFmpeg、默认配置等只读文件则从应用资源根目录解析。
"""

from __future__ import annotations

import os
from pathlib import Path
import sys


APPLICATION_NAME = "ZeroCaption"


def application_root() -> Path:
    """返回源码运行或 PyInstaller 运行时的只读资源根目录。"""

    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return Path(bundle_root)
    return Path(__file__).resolve().parents[1]


def resource_path(relative_path: str | Path) -> Path:
    """把相对资源路径解析到应用安装目录或 PyInstaller 临时目录。"""

    path = Path(relative_path)
    return path if path.is_absolute() else application_root() / path


def user_data_root() -> Path:
    """返回 Windows 用户可写的数据根目录，并确保目录存在。"""

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        root = Path(local_app_data)
    else:
        app_data = os.environ.get("APPDATA")
        root = Path(app_data) if app_data else Path.home() / "AppData" / "Local"
    target = root / APPLICATION_NAME
    target.mkdir(parents=True, exist_ok=True)
    return target


def user_data_path(relative_path: str | Path) -> Path:
    """把相对数据路径解析到用户数据目录，并确保父目录存在。"""

    path = Path(relative_path)
    target = path if path.is_absolute() else user_data_root() / path
    target.parent.mkdir(parents=True, exist_ok=True)
    return target
