"""创建项目时可读任务名称与目录隔离行为的单元测试。"""

from pathlib import Path

import core.usecases.create_project as create_project_module
from core.dto.project_dto import CreateProjectInput
from core.services.task_service import TaskService
from core.usecases.create_project import CreateProject
from infrastructure.storage.memory_repositories import (
    InMemoryProjectRepository,
    InMemoryTaskRepository,
)
from infrastructure.storage.workspace import WorkspaceManager


def _request(source_video: Path, workspace: WorkspaceManager) -> CreateProjectInput:
    """构造只包含命名测试所需字段的创建请求。"""

    return CreateProjectInput(
        source_video=source_video,
        source_language="auto",
        target_language="zh-CN",
        workspace_dir=workspace.root,
    )


def test_repeated_video_uses_two_character_suffix_and_separate_directories(
    tmp_path,
    monkeypatch,
) -> None:
    """同一视频重复创建时应显示不同后缀，并使用互不共享的项目目录。"""

    # arrange：固定随机起点为 `BC`，第二次创建会先碰撞，再继续使用 `BD`。
    monkeypatch.setattr(
        create_project_module.secrets,
        "randbelow",
        lambda _upper_bound: 38,
    )
    workspace = WorkspaceManager(tmp_path / "data")
    projects = InMemoryProjectRepository()
    tasks = InMemoryTaskRepository()
    usecase = CreateProject(
        project_repository=projects,
        task_repository=tasks,
        project_workspace=workspace,
    )
    source_video = tmp_path / "lesson.mp4"

    # act：用完全相同的视频路径连续创建两个项目。
    first = usecase.execute(_request(source_video, workspace))
    second = usecase.execute(_request(source_video, workspace))

    # assert：目录和界面名称都带两位后缀，且不会复用第一次的目录。
    assert first.project.workspace_dir.name == "lesson-BC"
    assert second.project.workspace_dir.name == "lesson-BD"
    assert first.project.workspace_dir != second.project.workspace_dir
    assert first.project.workspace_dir.is_dir()
    assert second.project.workspace_dir.is_dir()

    history = TaskService(
        project_repository=projects,
        task_repository=tasks,
    ).list_video_tasks()
    assert {item.display_name for item in history} == {
        "lesson-BC.mp4",
        "lesson-BD.mp4",
    }


def test_legacy_project_keeps_original_video_name_in_history(tmp_path) -> None:
    """旧目录仍使用项目编号时，任务列表应继续展示原视频文件名。"""

    workspace = WorkspaceManager(tmp_path / "data")
    projects = InMemoryProjectRepository()
    tasks = InMemoryTaskRepository()
    usecase = CreateProject(
        project_repository=projects,
        task_repository=tasks,
    )
    result = usecase.execute(_request(tmp_path / "legacy.mp4", workspace))

    history = TaskService(
        project_repository=projects,
        task_repository=tasks,
    ).list_video_tasks()

    assert result.project.workspace_dir == workspace.root
    assert history[0].display_name == "legacy.mp4"
