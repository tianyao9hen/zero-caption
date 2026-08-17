"""视频任务删除服务测试。

测试保护项目记录和项目文件夹必须一起消失，同时确认源视频和用户放在
项目目录外的成果不属于删除范围。
"""

from core.domain.entities import Project
from core.services.task_service import TaskService
from infrastructure.storage.memory_repositories import InMemoryProjectRepository
from infrastructure.storage.workspace import WorkspaceManager


def test_task_service_deletes_processing_project_and_its_directory(tmp_path) -> None:
    """处理中项目也允许删除，且不能误删项目目录外的文件。"""

    workspace = WorkspaceManager(tmp_path / "workspace")
    project_dir = workspace.ensure_project_structure("project-delete")
    (project_dir / "cache" / "partial.bin").write_bytes(b"cache")
    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"video")
    external_output = tmp_path / "exports" / "result.mp4"
    external_output.parent.mkdir()
    external_output.write_bytes(b"result")
    project = Project(
        project_id="project-delete",
        source_video=source_video,
        source_language="en",
        target_language="zh-CN",
        workspace_dir=project_dir,
        output_path=external_output,
    )
    project.mark_processing()
    projects = InMemoryProjectRepository()
    projects.save(project)
    service = TaskService(
        project_repository=projects,
        project_workspace=workspace,
    )

    service.delete_video_task(project.project_id)

    assert projects.get_by_id(project.project_id) is None
    assert project_dir.exists() is False
    assert source_video.is_file()
    assert external_output.is_file()
