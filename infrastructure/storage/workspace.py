"""工作区目录管理模块。

这个文件属于 infrastructure 层，因为它直接处理文件系统目录结构。
它应该知道应用数据放在哪里，但不应该决定任务什么时候开始或结束。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class WorkspaceManager:
    """暴露应用运行时会反复使用的固定目录。"""

    root: Path

    @property
    def projects_dir(self) -> Path:
        """返回未来存放项目级数据的目录。"""

        return self.root / "projects"

    @property
    def cache_dir(self) -> Path:
        """返回存放可复用中间产物的目录。"""

        return self.root / "cache"

    @property
    def exports_dir(self) -> Path:
        """返回存放最终导出文件的目录。"""

        return self.root / "exports"

    @property
    def logs_dir(self) -> Path:
        """返回应用级日志目录。

        当前它放在 data 根目录之外，这样在开发早期查看日志更直接。
        """

        return Path("logs")

    def ensure_structure(self) -> None:
        """创建当前骨架版本运行所需的基础目录结构。"""

        # 先创建根目录，这样后面的子目录都能基于一个确定的父路径创建。
        self.root.mkdir(parents=True, exist_ok=True)

        # 这里显式逐个创建目录，而不是先拼一个列表再循环。
        # 代码虽然长一点，但对 Python 初学者更容易读懂。
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.exports_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
