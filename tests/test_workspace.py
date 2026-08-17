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


def test_workspace_creates_readable_unique_project_directory(tmp_path):
    """新任务目录应使用可读名称，并写入可供删除校验的项目身份标记。"""

    workspace = WorkspaceManager(tmp_path / "data")

    project_dir = workspace.create_project_structure(
        "project-readable",
        "lesson-AB",
    )

    assert project_dir == workspace.projects_dir / "lesson-AB"
    assert (project_dir / ".zero-caption-project").read_text(
        encoding="utf-8"
    ) == "project-readable\n"
    assert (project_dir / "subtitles").is_dir()


def test_workspace_refuses_duplicate_readable_project_directory(tmp_path):
    """同名任务目录已经存在时必须报告冲突，不能复用其中的缓存文件。"""

    workspace = WorkspaceManager(tmp_path / "data")
    first = workspace.create_project_structure("project-first", "lesson-AB")

    with pytest.raises(FileExistsError):
        workspace.create_project_structure("project-second", "lesson-AB")

    assert (first / ".zero-caption-project").read_text(
        encoding="utf-8"
    ) == "project-first\n"


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


def test_workspace_deletes_only_exact_project_directory(tmp_path):
    """项目清理只能删除编号和持久化路径都严格匹配的目录。"""

    workspace = WorkspaceManager(tmp_path / "data")
    project_dir = workspace.ensure_project_structure("project-delete")
    artifact = project_dir / "subtitles" / "translated.srt"
    artifact.write_text("测试字幕", encoding="utf-8")

    workspace.delete_project_structure("project-delete", project_dir)

    assert project_dir.exists() is False
    assert workspace.projects_dir.exists() is True


def test_workspace_deletes_readable_directory_only_for_matching_project(tmp_path):
    """可读任务目录必须通过身份标记核对后才能递归删除。"""

    workspace = WorkspaceManager(tmp_path / "data")
    project_dir = workspace.create_project_structure(
        "project-readable",
        "lesson-AB",
    )

    with pytest.raises(ValueError, match="身份标记不匹配"):
        workspace.delete_project_structure("project-other", project_dir)

    assert project_dir.is_dir()
    workspace.delete_project_structure("project-readable", project_dir)
    assert project_dir.exists() is False


def test_workspace_refuses_mismatched_project_directory(tmp_path):
    """调用方传错项目目录时必须拒绝递归删除，保护其他项目数据。"""

    workspace = WorkspaceManager(tmp_path / "data")
    other_project = workspace.ensure_project_structure("project-other")

    with pytest.raises(ValueError, match="不匹配"):
        workspace.delete_project_structure("project-delete", other_project)

    assert other_project.exists() is True
