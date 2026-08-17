"""工作区目录管理模块。

这个文件属于 infrastructure 层，因为它直接处理文件系统目录结构。
它应该知道应用数据放在哪里，但不应该决定任务什么时候开始或结束。
"""

from __future__ import annotations

from dataclasses import dataclass
import shutil
from pathlib import Path


@dataclass(slots=True)
class WorkspaceManager:
    """暴露应用运行时会反复使用的固定目录。"""

    root: Path

    _marker_name = ".zero-caption-workspace"
    _marker_content = "zero-caption-workspace-v1\n"
    _project_marker_name = ".zero-caption-project"
    _project_subdirs = (
        "source",
        "temp",
        "cache",
        "subtitles",
        "exports",
        "logs",
    )

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
    def database_path(self) -> Path:
        """返回应用 SQLite 文件路径，和工作区一起迁移。"""

        return self.root / "zero_caption.sqlite3"

    @property
    def logs_dir(self) -> Path:
        """返回应用级日志目录。

        日志和数据库一起放入用户工作区，避免安装版从当前工作目录启动时
        把可写文件落到 `Program Files` 或用户不认识的目录中。
        """

        return self.root / "logs"

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

        # 标记文件用于证明这个目录曾由应用初始化。删除旧工作区时必须先验证
        # 该标记，避免因为用户手工输入了普通文件夹而误删个人数据。
        marker = self.root / self._marker_name
        if not marker.exists():
            marker.write_text(self._marker_content, encoding="utf-8")

    def ensure_project_structure(self, project_id: str) -> Path:
        """创建并返回指定项目的标准工作目录结构。"""

        self.ensure_structure()

        project_dir = self.projects_dir / project_id
        project_dir.mkdir(parents=True, exist_ok=True)

        for dirname in self._project_subdirs:
            (project_dir / dirname).mkdir(parents=True, exist_ok=True)

        return project_dir

    def create_project_structure(
        self,
        project_id: str,
        directory_name: str,
    ) -> Path:
        """以用户可读名称创建一个全新的项目目录。

        参数：
            project_id：数据库使用的稳定项目编号。
            directory_name：由视频名和随机后缀组成的目录名。

        返回：
            新创建的项目根目录。

        副作用：
            会创建项目目录、身份标记和标准子目录。若同名目录已经存在，
            `mkdir` 会抛出 `FileExistsError`，调用方可以换一个后缀重试。
        """

        if not project_id:
            raise ValueError("项目编号不能为空。")
        if (
            not directory_name
            or Path(directory_name).name != directory_name
            or directory_name in {".", ".."}
        ):
            raise ValueError("项目目录名包含无效的路径字符。")

        self.ensure_structure()
        project_dir = self.projects_dir / directory_name

        # 第一步：用独占创建检测同名目录，避免两个并发任务共用缓存和字幕。
        project_dir.mkdir(exist_ok=False)
        try:
            # 第二步：身份标记把可读目录名和内部项目编号关联起来。
            # 删除任务时会核对这个标记，避免误删另一个项目的同名目录。
            marker = project_dir / self._project_marker_name
            marker.write_text(f"{project_id}\n", encoding="utf-8")

            # 第三步：只有身份标记写入成功后才创建标准子目录。
            for dirname in self._project_subdirs:
                (project_dir / dirname).mkdir()
        except Exception:
            # 目录是本方法刚刚独占创建的；初始化失败时回滚半成品，
            # 后续重试才不会把它误判为一个有效的既有项目。
            shutil.rmtree(project_dir)
            raise

        return project_dir

    def delete_project_structure(
        self,
        project_id: str,
        project_dir: Path,
    ) -> None:
        """只删除工作区中身份信息与项目编号匹配的项目目录。

        参数：
            project_id：数据库记录中的项目编号。
            project_dir：项目创建时持久化的实际目录。

        副作用：
            目标存在且通过边界校验后会递归删除。源视频通常位于工作区外，
            不在这个方法的删除范围内。
        """

        if not project_id or Path(project_id).name != project_id:
            raise ValueError("项目编号包含无效的路径字符，拒绝删除目录。")

        projects_root = self.projects_dir
        raw_target = Path(project_dir).expanduser()
        target = raw_target.resolve()
        resolved_projects_root = projects_root.resolve()
        if target.parent != resolved_projects_root:
            raise ValueError("项目目录与工作区记录不匹配，拒绝自动删除。")

        # 目录联接和符号链接可能把看似位于工作区内的路径指向其他磁盘位置。
        # 删除前同时检查项目根和目标本身，避免递归操作越过工作区边界。
        is_junction = getattr(raw_target, "is_junction", lambda: False)
        root_is_junction = getattr(projects_root, "is_junction", lambda: False)
        if (
            projects_root.is_symlink()
            or root_is_junction()
            or raw_target.is_symlink()
            or is_junction()
        ):
            raise ValueError("项目目录使用了链接或目录联接，拒绝自动删除。")

        if not raw_target.exists():
            return
        if not raw_target.is_dir():
            raise ValueError("项目工作路径不是普通目录，拒绝自动删除。")

        # 新项目使用可读目录名，因此通过目录内标记核对项目编号。
        # 旧版本没有标记，仍要求目录名与项目编号完全相同，保持兼容和安全。
        marker = raw_target / self._project_marker_name
        if marker.exists():
            if (
                not marker.is_file()
                or marker.read_text(encoding="utf-8") != f"{project_id}\n"
            ):
                raise ValueError("项目目录身份标记不匹配，拒绝自动删除。")
        elif raw_target.name != project_id:
            raise ValueError("项目目录与工作区记录不匹配，拒绝自动删除。")
        shutil.rmtree(raw_target)

    def delete_managed_workspace(self, current_root: str | Path) -> None:
        """永久删除一个已经停用且可安全识别的工作区。

        参数：
            current_root：应用当前正在使用的工作区，用于阻止误删新目录。

        副作用：
            验证通过后会递归删除旧工作区。目录缺少应用标记、包含未知的
            顶层文件，或与当前工作区存在包含关系时都会拒绝自动删除。
        """

        target = self.root.expanduser().resolve()
        current = Path(current_root).expanduser().resolve()

        # 第一步：保护仍在使用的目录、磁盘根目录以及当前目录和用户目录的祖先。
        # 这些路径一旦误删影响范围过大，只允许用户在应用外手工处理。
        if target == current:
            raise ValueError("不能删除当前正在使用的工作区。")
        if target in current.parents or current in target.parents:
            raise ValueError("新旧工作区存在包含关系，不能自动删除旧目录。")
        if target == Path(target.anchor):
            raise ValueError("不能把磁盘根目录作为可自动删除的工作区。")

        protected_paths = (Path.home().resolve(), Path.cwd().resolve())
        if any(target == path or target in path.parents for path in protected_paths):
            raise ValueError("旧工作区范围过大，不能由应用自动删除。")

        # 第二步：只处理普通目录，并拒绝跟随符号链接或 Windows 目录联接。
        if not target.exists():
            return
        is_junction = getattr(target, "is_junction", lambda: False)
        if not target.is_dir() or target.is_symlink() or is_junction():
            raise ValueError("旧工作区不是可安全删除的普通目录。")

        # 第三步：应用标记必须内容完全匹配，不能只凭同名文件判断目录归属。
        marker = target / self._marker_name
        if (
            not marker.is_file()
            or marker.read_text(encoding="utf-8") != self._marker_content
        ):
            raise ValueError("旧目录缺少有效的 Zero Caption 工作区标记。")

        # 第四步：顶层只允许出现应用自己管理的目录和文件。
        # 项目内部可以包含任意媒体产物，但普通用户文件夹不会因此被整体误删。
        managed_names = {
            self._marker_name,
            "projects",
            "cache",
            "exports",
            "logs",
            "models",
            "temp",
            "zero_caption.sqlite3",
            "desktop.ini",
            "Thumbs.db",
        }
        unexpected_names = sorted(
            child.name for child in target.iterdir() if child.name not in managed_names
        )
        if unexpected_names:
            preview = "、".join(unexpected_names[:3])
            raise ValueError(f"旧目录包含非工作区文件：{preview}。请手工确认后删除。")

        shutil.rmtree(target)
