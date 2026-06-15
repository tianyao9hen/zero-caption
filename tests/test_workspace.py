"""工作区目录创建相关测试。"""

from infrastructure.storage.workspace import WorkspaceManager


def test_workspace_creates_directories(tmp_path):
    """`ensure_structure` 应创建所有共享顶层目录。"""

    workspace = WorkspaceManager(tmp_path / "data")
    workspace.ensure_structure()
    assert workspace.projects_dir.exists()
    assert workspace.cache_dir.exists()
    assert workspace.exports_dir.exists()
    assert workspace.logs_dir.exists()


def test_workspace_creates_project_level_directories(tmp_path):
    """项目目录下应创建全部标准子目录。"""

    workspace = WorkspaceManager(tmp_path / "data")
    workspace.ensure_structure()

    project_dir = workspace.ensure_project_structure("project-001")

    assert project_dir == workspace.projects_dir / "project-001"
    assert (project_dir / "source").exists()
    assert (project_dir / "temp").exists()
    assert (project_dir / "cache").exists()
    assert (project_dir / "subtitles").exists()
    assert (project_dir / "exports").exists()
    assert (project_dir / "logs").exists()
