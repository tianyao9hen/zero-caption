"""Windows 发布清单的静态契约测试。

真实安装和启动由 PowerShell 验收脚本负责，这里用快速单元测试保护几个容易在维护时
被误删的发布约束：可选安装目录、完整复制便携目录、安全卸载以及隔离环境验收。
"""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_installer_manifest_copies_complete_portable_directory() -> None:
    """安装清单应递归复制发布目录，并始终向用户展示目录选择页面。"""

    manifest = (PROJECT_ROOT / "installer" / "ZeroCaption.iss").read_text(
        encoding="utf-8-sig"
    )

    assert "DefaultDirName={localappdata}\\Programs\\ZeroCaption" in manifest
    assert "DisableDirPage=no" in manifest
    assert "PrivilegesRequired=lowest" in manifest
    assert '#define MyPayloadSource "..\\dist\\ZeroCaption\\*"' in manifest
    assert '#ifdef InstallerSmokeTest' in manifest
    assert "recursesubdirs" in manifest
    assert 'DestName: "{#MyInstallMarkerName}"' in manifest
    assert "IsSafeInstallDirectory(InstallDirectory)" in manifest
    assert "if WizardSilent then" in manifest
    assert "procedure CurStepChanged(CurStep: TSetupStep);" in manifest
    assert "if CurStep <> ssInstall then" in manifest
    assert "Abort;" in manifest
    assert "UninstallDisplayName={#MyAppName}" in manifest


def test_uninstaller_clears_install_files_and_asks_before_history_cleanup() -> None:
    """卸载器应清空应用目录，但只有用户明确同意后才删除本机历史记录。"""

    manifest = (PROJECT_ROOT / "installer" / "ZeroCaption.iss").read_text(
        encoding="utf-8-sig"
    )

    assert 'Type: filesandordirs; Name: "{app}\\*"' in manifest
    assert 'Type: dirifempty; Name: "{app}"' in manifest
    assert "function InitializeUninstall(): Boolean;" in manifest
    assert "是否同时清理 Zero Caption 的历史记录" in manifest
    assert "MB_YESNO or MB_DEFBUTTON2" in manifest
    assert "if not UninstallSilent then" in manifest
    assert "'/CLEANHISTORY'" in manifest
    assert "IsSafeTestHistoryDirectory(TestHistoryDirectory)" in manifest
    assert "'{param:TESTHISTORYROOT|}'" in manifest
    assert "DelTree(UserDataDirectory, True, True, True)" in manifest


def test_installer_verifier_covers_both_history_cleanup_choices() -> None:
    """安装包验收应覆盖自选目录、保留历史以及显式清理历史三条路径。"""

    verifier = (
        PROJECT_ROOT / "scripts" / "verify_installer.ps1"
    ).read_text(encoding="utf-8-sig")

    assert "custom install location\\Zero Caption" in verifier
    assert "Assert-RejectsUnsafeInstallDirectory" in verifier
    assert "personal-file.txt" in verifier
    assert "history-preserved.marker" in verifier
    assert "runtime-generated-residue.tmp" in verifier
    assert "$uninstallArguments += '/CLEANHISTORY'" in verifier
    assert "-TestHistoryDirectory $historyRoot" in verifier
    assert "选择清理后仍残留历史记录目录" in verifier


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
    assert "bundled_models" in build_script


def test_release_bundle_includes_small_and_medium_models() -> None:
    """PyInstaller 与安装验收都应覆盖两套可选识别模型。"""

    spec = (PROJECT_ROOT / "ZeroCaption.spec").read_text(encoding="utf-8-sig")
    verifier = (
        PROJECT_ROOT / "scripts" / "verify_installer.ps1"
    ).read_text(encoding="utf-8-sig")

    assert 'bundled_models = tomllib.load' in spec
    assert 'resources\\models\\small\\model.bin' in verifier
    assert 'resources\\models\\medium\\model.bin' in verifier


def test_release_bundle_includes_cuda_runtime_libraries() -> None:
    """发布包应显式收集真实 GPU 推理阶段才会加载的 `cuBLAS 12`。"""

    project = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    spec = (PROJECT_ROOT / "ZeroCaption.spec").read_text(encoding="utf-8-sig")
    verifier = (
        PROJECT_ROOT / "scripts" / "verify_installer.ps1"
    ).read_text(encoding="utf-8-sig")

    assert "nvidia-cublas-cu12==12.6.4.1" in project
    assert 'collect_dynamic_libs("nvidia.cublas")' in spec
    assert "cublas64_12.dll" in verifier
    assert "cublasLt64_12.dll" in verifier
