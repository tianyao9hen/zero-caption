"""项目工作区与文件指纹抽象端口。

目录创建和文件读取都属于基础设施行为。
核心用例只通过端口请求这些能力，从而保持对文件系统实现的隔离。
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class ProjectWorkspace(Protocol):
    """创建和安全删除项目级标准目录结构的能力。"""

    def create_project_structure(
        self,
        project_id: str,
        directory_name: str,
    ) -> Path:
        """使用指定目录名创建全新的项目目录，目录已存在时报告冲突。"""

        ...

    def ensure_project_structure(self, project_id: str) -> Path:
        """创建项目目录和标准子目录，并返回项目根目录。"""

        ...

    def delete_project_structure(
        self,
        project_id: str,
        project_dir: Path,
    ) -> None:
        """校验并递归删除指定项目目录，不影响源视频或工作区其他项目。"""

        ...


class FileFingerprintCalculator(Protocol):
    """以流式方式计算源文件稳定指纹的能力。"""

    def calculate(self, source_path: Path) -> str:
        """读取源文件并返回可用于缓存判断的指纹。"""

        ...
