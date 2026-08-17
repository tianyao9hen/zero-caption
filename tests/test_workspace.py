"""工作区目录创建相关测试。"""

import pytest

from infrastructure.storage.workspace import WorkspaceManager


def test_workspace_creates_directories(tmp_path):
    """`ensure_structure` 应创建所有共享顶层目录。"""

    workspace = WorkspaceManager(tmp_path / "data")
    workspace.ensure_structure()
    assert workspace.projects_dir.exists()
    assert workspace.cache_dir.exists()
    assert workspace.exports_dir.exists()
    assert workspace.logs_dir.exists()
    assert workspace.logs_dir == workspace.root / "logs"


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


def test_workspace_deletes_only_marked_managed_directory(tmp_path):
    """用户确认后，应能删除只包含应用数据且已经停用的旧工作区。"""

    # arrange：旧目录由管理器完整初始化，项目文件位于受管理的 `projects` 中。
    old_workspace = WorkspaceManager(tmp_path / "old-workspace")
    old_workspace.ensure_structure()
    project_dir = old_workspace.ensure_project_structure("project-001")
    (project_dir / "subtitles" / "translated.srt").write_text(
        "测试字幕",
        encoding="utf-8",
    )
    current_workspace = WorkspaceManager(tmp_path / "current-workspace")
    current_workspace.ensure_structure()

    # act
    old_workspace.delete_managed_workspace(current_workspace.root)

    # assert
    assert old_workspace.root.exists() is False
    assert current_workspace.root.exists() is True


def test_workspace_refuses_to_delete_directory_with_unknown_files(tmp_path):
    """旧目录混有普通用户文件时，应拒绝整目录自动删除。"""

    old_workspace = WorkspaceManager(tmp_path / "mixed-workspace")
    old_workspace.ensure_structure()
    personal_file = old_workspace.root / "personal-document.txt"
    personal_file.write_text("不能误删", encoding="utf-8")
    current_workspace = WorkspaceManager(tmp_path / "current-workspace")
    current_workspace.ensure_structure()

    with pytest.raises(ValueError, match="非工作区文件"):
        old_workspace.delete_managed_workspace(current_workspace.root)

    assert personal_file.is_file()
