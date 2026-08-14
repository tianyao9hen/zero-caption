"""项目工作区与文件指纹抽象端口。

目录创建和文件读取都属于基础设施行为。
核心用例只通过端口请求这些能力，从而保持对文件系统实现的隔离。
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class ProjectWorkspace(Protocol):
    """创建项目级标准目录结构的能力。"""

    def ensure_project_structure(self, project_id: str) -> Path:
        """创建项目目录和标准子目录，并返回项目根目录。"""

        ...


class FileFingerprintCalculator(Protocol):
    """以流式方式计算源文件稳定指纹的能力。"""

    def calculate(self, source_path: Path) -> str:
        """读取源文件并返回可用于缓存判断的指纹。"""

        ...
