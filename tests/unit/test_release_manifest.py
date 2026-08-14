"""Windows 发布清单的静态契约测试。

真实安装和启动由 PowerShell 验收脚本负责，这里用快速单元测试保护几个容易在维护时
被误删的发布约束：单用户安装、完整复制便携目录、生成卸载程序以及隔离环境验收。
"""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_installer_manifest_copies_complete_portable_directory() -> None:
    """安装清单应递归复制完整发布目录，并使用无管理员权限的用户安装位置。"""

    manifest = (PROJECT_ROOT / "installer" / "ZeroCaption.iss").read_text(
        encoding="utf-8-sig"
    )

    assert "DefaultDirName={localappdata}\\Programs\\ZeroCaption" in manifest
    assert "PrivilegesRequired=lowest" in manifest
    assert 'Source: "..\\dist\\ZeroCaption\\*"' in manifest
    assert "recursesubdirs" in manifest
    assert "UninstallDisplayName={#MyAppName}" in manifest


def test_release_verifier_removes_local_development_dependencies() -> None:
    """发布验收应清除本机 Python 与模型缓存提示，并启用离线模型模式。"""

    verifier = (
        PROJECT_ROOT / "scripts" / "verify_packaged_app.ps1"
    ).read_text(encoding="utf-8-sig")

    for variable_name in (
        "PYTHONHOME",
        "PYTHONPATH",
        "VIRTUAL_ENV",
        "CONDA_PREFIX",
        "HUGGINGFACE_HUB_CACHE",
    ):
        assert f"'{variable_name}'" in verifier
    assert "$env:HF_HUB_OFFLINE = '1'" in verifier
    assert "$env:TRANSFORMERS_OFFLINE = '1'" in verifier
    assert "-ArgumentList '-version'" in verifier


def test_build_script_creates_and_verifies_installer() -> None:
    """一键构建入口应同时生成校验和并执行安装后的验收脚本。"""

    build_script = (PROJECT_ROOT / "scripts" / "build_windows.ps1").read_text(
        encoding="utf-8-sig"
    )

    assert "installer\\ZeroCaption.iss" in build_script
    assert "Get-FileHash" in build_script
    assert "verify_installer.ps1" in build_script
