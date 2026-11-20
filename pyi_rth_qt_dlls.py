"""发布运行时钩子：在应用导入 Qt 前注册随包提供的 DLL 目录。"""

from __future__ import annotations

import os
import sys
from pathlib import Path


# `add_dll_directory` 返回的句柄必须保持存活，否则 Windows 会移除已注册路径。
_dll_directory_handles = []


def _bundle_directory(name: str) -> Path | None:
    """查找 PyInstaller 单目录包和旧版目录布局中的 DLL 子目录。"""

    bundle_root = Path(sys._MEIPASS)
    candidates = (
        (bundle_root / "_internal" / name),
        (bundle_root / name),
    )
    return next((directory for directory in candidates if directory.is_dir()), None)

if sys.platform == "win32":
    # PyInstaller 6 的单目录包把依赖放在 `_internal`，旧版布局则直接放在包根目录。
    # 只注册 Qt 自身目录，避免把整个 `_internal` 放入搜索路径后误加载其他运行库。
    for package_name in ("PySide6", "shiboken6"):
        directory = _bundle_directory(package_name)
        if directory is not None:
            _dll_directory_handles.append(os.add_dll_directory(str(directory)))

    # PyInstaller 可能从其他扩展包收集不同版本的 VC 运行库到 `_internal` 根目录。
    # Windows 会按搜索路径解析尚未加载的同名 DLL，因此把 Qt wheel 自带目录
    # 提到 PATH 前面，确保 PySide6、shiboken6 与其 VC 运行库来自同一套发行物。
    bundled_qt_directories = [
        str(directory)
        for package_name in ("PySide6", "shiboken6")
        if (directory := _bundle_directory(package_name)) is not None
    ]
    if bundled_qt_directories:
        os.environ["PATH"] = os.pathsep.join(
            [*bundled_qt_directories, os.environ.get("PATH", "")]
        )
