"""应用资源路径和用户数据路径测试。

这些测试保护源码运行与 PyInstaller 运行之间最容易出错的目录边界：
只读资源从程序目录读取，可写数据始终进入当前用户目录。
"""

from pathlib import Path
import sys

from app.bootstrap import _resolve_runtime_settings
from config.paths import application_root, resource_path, user_data_path
from config.settings import Settings


def test_application_root_uses_pyinstaller_bundle_directory(tmp_path, monkeypatch):
    """PyInstaller 提供 `_MEIPASS` 时，资源路径应从解包目录解析。"""

    # arrange / act：测试环境手工模拟 PyInstaller 注入的运行时属性。
    bundle_root = tmp_path / "bundle"
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle_root), raising=False)

    # assert：所有相对资源都必须落在只读的打包资源根目录下。
    assert application_root() == bundle_root
    assert resource_path("config/default.toml") == bundle_root / "config/default.toml"


def test_user_data_path_uses_local_app_data_and_creates_parent(tmp_path, monkeypatch):
    """相对用户数据路径应落入 `%LOCALAPPDATA%\\ZeroCaption`。"""

    # arrange / act
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    target = user_data_path("nested/settings.toml")

    # assert：函数只创建父目录，不会伪造尚未写入的文件。
    assert target == tmp_path / "ZeroCaption" / "nested" / "settings.toml"
    assert target.parent.is_dir()
    assert not target.exists()


def test_runtime_settings_separate_bundled_tools_and_writable_data(
    tmp_path,
    monkeypatch,
):
    """启动解析应把工作区放到用户目录，并把随包工具解析成绝对路径。"""

    # arrange：默认配置使用相对路径，正是安装版首次启动时的输入形态。
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    # act
    resolved = _resolve_runtime_settings(Settings())

    # assert：默认命令在资源不存在时仍保留 PATH 回退，可写路径则必须绝对化。
    assert resolved.workspace_root == tmp_path / "ZeroCaption" / "data"
    assert resolved.runtime.model_cache_dir == tmp_path / "ZeroCaption" / "data" / "models"
    assert resolved.runtime.ffmpeg_path == "ffmpeg"
    assert Path(resolved.workspace_root).is_absolute()
