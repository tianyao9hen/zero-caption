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
