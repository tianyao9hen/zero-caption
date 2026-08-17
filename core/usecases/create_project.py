"""创建项目用例模块。

这个文件属于 `core/usecases`，负责把“导入一个视频并建立项目”这件事
表达成一个明确的业务用例。它可以依赖仓储和事件端口，
但不能直接依赖 UI 或具体基础设施实现。
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
import secrets
import string
from uuid import uuid4

from core.domain.entities import Project, Task
from core.domain.enums import TaskCheckpoint
from core.dto.project_dto import CreateProjectInput, CreateProjectResult
from core.ports.events import TaskEventPublisher
from core.ports.repository import ProjectRepository, TaskRepository
from core.ports.workspace import FileFingerprintCalculator, ProjectWorkspace


_PROJECT_SUFFIX_ALPHABET = string.ascii_uppercase + string.digits
_PROJECT_SUFFIX_SPACE = len(_PROJECT_SUFFIX_ALPHABET) ** 2


def _project_directory_candidates(video_stem: str) -> Iterator[str]:
    """按随机起点生成全部两位后缀候选名称。

    首个候选保持随机；发生碰撞后继续遍历剩余组合。这样既符合用户看到的
    随机命名，也不会因为一次随机重复就让两个任务共用同一个目录。
    """

    start = secrets.randbelow(_PROJECT_SUFFIX_SPACE)
    alphabet_size = len(_PROJECT_SUFFIX_ALPHABET)
    for offset in range(_PROJECT_SUFFIX_SPACE):
        value = (start + offset) % _PROJECT_SUFFIX_SPACE
        first, second = divmod(value, alphabet_size)
        suffix = (
            _PROJECT_SUFFIX_ALPHABET[first]
            + _PROJECT_SUFFIX_ALPHABET[second]
        )
        yield f"{video_stem}-{suffix}"


@dataclass(slots=True)
class CreateProject:
    """负责创建项目实体、项目目录和初始化任务快照。"""

    project_repository: ProjectRepository
    task_repository: TaskRepository
    event_publisher: TaskEventPublisher | None = None
    project_workspace: ProjectWorkspace | None = None
    fingerprint_calculator: FileFingerprintCalculator | None = None

    def execute(self, request: CreateProjectInput) -> CreateProjectResult:
        """执行项目创建流程。"""

        # 第一步：校验输入，确保后续实体创建建立在有效路径之上。
        if not request.source_video.name:
            raise ValueError("源视频路径不能为空。")

        # 第二步：内部项目编号仍使用 UUID，避免可读名称承担数据库主键职责。
        # 项目目录改为“视频名-两位随机字符串”，便于用户辨认重复创建的任务。
        project_id = f"project-{uuid4().hex}"
        workspace_dir = request.workspace_dir
        if self.project_workspace is not None:
            for directory_name in _project_directory_candidates(
                request.source_video.stem
            ):
                try:
                    workspace_dir = self.project_workspace.create_project_structure(
                        project_id,
                        directory_name,
                    )
                except FileExistsError:
                    continue
                break
            else:
                raise RuntimeError("两位随机后缀已经全部被占用，无法创建项目。")

        # 第三步：按需计算源文件指纹。
        # 指纹计算会流式读取文件，具体算法留在基础设施层，
        # 后续缓存只需要比较这个稳定字符串，不需要再次加载整个视频。
        source_fingerprint = ""
        if self.fingerprint_calculator is not None:
            source_fingerprint = self.fingerprint_calculator.calculate(request.source_video)

        # 第四步：创建项目实体，并立刻推进到“已导入”检查点。
        project = Project(
            project_id=project_id,
            source_video=request.source_video,
            source_language=request.source_language,
            target_language=request.target_language,
            workspace_dir=workspace_dir,
            source_fingerprint=source_fingerprint,
            translation_context=request.translation_context.strip(),
            processing_mode=request.processing_mode,
            export_mode=request.export_mode,
            output_path=request.output_path,
        )
        project.mark_imported()

        # 第五步：为这次导入生成一个已完成任务，并先保存再发布事件。
        task = Task(
            task_id=f"task-{uuid4().hex}",
            project_id=project.project_id,
            task_type="create_project",
        )
        task.start("开始导入项目")
        task.mark_succeeded("项目已导入", checkpoint=TaskCheckpoint.IMPORTED)

        self.project_repository.save(project)
        self.task_repository.save(task)
        if self.event_publisher is not None:
            self.event_publisher.publish(task)

        return CreateProjectResult(project=project, task=task)
