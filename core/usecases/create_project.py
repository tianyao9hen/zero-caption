"""创建项目用例模块。

这个文件属于 `core/usecases`，负责把“导入一个视频并建立项目”这件事
表达成一个明确的业务用例。它可以依赖仓储和事件端口，
但不能直接依赖 UI 或具体基础设施实现。
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from core.domain.entities import Project, Task
from core.domain.enums import TaskCheckpoint
from core.dto.project_dto import CreateProjectInput, CreateProjectResult
from core.ports.events import TaskEventPublisher
from core.ports.repository import ProjectRepository, TaskRepository


@dataclass(slots=True)
class CreateProject:
    """负责创建项目实体和初始化任务快照。"""

    project_repository: ProjectRepository
    task_repository: TaskRepository
    event_publisher: TaskEventPublisher | None = None

    def execute(self, request: CreateProjectInput) -> CreateProjectResult:
        """执行项目创建流程。"""

        # 第一步：校验输入，确保后续实体创建建立在有效路径之上。
        if not request.source_video.name:
            raise ValueError("源视频路径不能为空。")

        # 第二步：创建项目实体，并立刻推进到“已导入”检查点。
        project = Project(
            project_id=f"project-{uuid4().hex}",
            source_video=request.source_video,
            source_language=request.source_language,
            target_language=request.target_language,
            workspace_dir=request.workspace_dir,
        )
        project.mark_imported()

        # 第三步：为这次导入生成一个已完成任务。
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
