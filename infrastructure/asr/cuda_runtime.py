"""Windows CUDA 动态库准备辅助模块。

这个文件属于基础设施层，负责把随 Python 包或发布包提供的 `cuBLAS 12`
目录加入当前进程的动态库搜索路径。核心层和界面层不应该知道 DLL 的目录结构；
它们只消费识别引擎最终报告的实际设备和回退结果。
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any

from config.paths import resource_path


# `os.add_dll_directory` 返回的句柄在关闭或被回收后会失效，因此必须让它们
# 与应用进程保持同样长的生命周期。集合用于避免重复注册同一个目录。
_DLL_DIRECTORY_HANDLES: list[Any] = []
_REGISTERED_DIRECTORIES: set[Path] = set()


def prepare_cuda_runtime() -> tuple[Path, ...]:
    """注册当前安装中可用的 `cuBLAS 12` 动态库目录。

    返回：
        已确认包含 `cublas64_12.dll` 的目录。非 Windows 平台直接返回空元组。

    副作用：
        在 Windows 上更新当前进程的 DLL 搜索目录和 `PATH`。这只影响应用进程，
        不会修改系统环境变量，也不要求用户安装完整 CUDA Toolkit。
    """

    if os.name != "nt":
        return ()

    available_directories: list[Path] = []
    for directory in _candidate_directories():
        resolved = directory.resolve()
        if not (resolved / "cublas64_12.dll").is_file():
            continue
        available_directories.append(resolved)
        if resolved in _REGISTERED_DIRECTORIES:
            continue

        # `os.add_dll_directory` 是 Python 3.8 起推荐的 Windows DLL 注册方式。
        # 同时补充当前进程的 `PATH`，是因为 `CTranslate2` 的原生代码会在真正
        # 开始 GPU 推理时自行加载 `cuBLAS`，不同版本采用的加载方式并不完全相同。
        add_directory = getattr(os, "add_dll_directory", None)
        if add_directory is not None:
            _DLL_DIRECTORY_HANDLES.append(add_directory(str(resolved)))
        _prepend_process_path(resolved)
        _REGISTERED_DIRECTORIES.add(resolved)
    return tuple(available_directories)


def _candidate_directories() -> tuple[Path, ...]:
    """返回开发环境和 PyInstaller 发布环境中的候选 DLL 目录。"""

    candidates: list[Path] = []
    try:
        specification = importlib.util.find_spec("nvidia.cublas")
    except (ImportError, ModuleNotFoundError, ValueError):
        specification = None
    if specification is not None and specification.submodule_search_locations:
        for package_directory in specification.submodule_search_locations:
            candidates.append(Path(package_directory) / "bin")

    # PyInstaller 会把 DLL 放入 `_MEIPASS/nvidia/cublas/bin`。
    # `resource_path` 同时兼容开发目录和发布目录，避免在这里直接判断打包状态。
    candidates.append(resource_path(Path("nvidia/cublas/bin")))
    return tuple(dict.fromkeys(candidates))


def _prepend_process_path(directory: Path) -> None:
    """把目录加入当前进程 `PATH`，并保持原有目录顺序不变。"""

    current_entries = [
        entry
        for entry in os.environ.get("PATH", "").split(os.pathsep)
        if entry
    ]
    normalized = os.path.normcase(str(directory))
    if any(os.path.normcase(entry) == normalized for entry in current_entries):
        return
    os.environ["PATH"] = os.pathsep.join([str(directory), *current_entries])
