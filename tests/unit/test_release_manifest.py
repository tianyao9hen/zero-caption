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
    assert "[System.Text.Encoding]::UTF8" in verifier
    assert "MainWindowHandle" in verifier
    assert "packaged GUI exited before creating a window" in verifier


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


def test_release_bundle_registers_qt_dll_paths_before_import() -> None:
    """发布程序应在导入 Qt 前注册 PySide6 和 shiboken6 的 DLL 目录。"""

    spec = (PROJECT_ROOT / "ZeroCaption.spec").read_text(encoding="utf-8-sig")
    runtime_hook = (PROJECT_ROOT / "pyi_rth_qt_dlls.py").read_text(
        encoding="utf-8-sig"
    )
    verifier = (
        PROJECT_ROOT / "scripts" / "verify_packaged_app.ps1"
    ).read_text(encoding="utf-8-sig")

    assert 'runtime_hooks=[str(repo_root / "pyi_rth_qt_dlls.py")]' in spec
    assert 'bundle_root / "_internal" / name' in runtime_hook
    assert 'bundle_root / name' in runtime_hook
    assert 'bundle_root,' not in runtime_hook
    assert 'os.environ["PATH"] = os.pathsep.join(' in runtime_hook
    assert 'os.add_dll_directory(str(directory))' in runtime_hook
    assert "--verify-qt-import" in verifier
    assert "MainWindowHandle" in verifier
    assert "packaged GUI exited before creating a window" in verifier


def test_release_bundle_excludes_external_libheif_vc_runtime_conflicts() -> None:
    """发布包不能把外部 libheif 的 VC 运行库平铺到 Qt DLL 搜索根目录。"""

    spec = (PROJECT_ROOT / "ZeroCaption.spec").read_text(encoding="utf-8-sig")

    assert '"vcruntime140.dll"' in spec
    assert '"msvcp140.dll"' in spec
    assert '"vcruntime140_1.dll"' in spec
    assert '"poppler"' in spec
    assert 'conflicting_external_parts = {"libheif", "poppler"}' in spec
    assert 'any(part.casefold() in conflicting_external_parts for part in Path(source).parts)' in spec
    # 二次清理必须复用同一套判断，避免两份规则各自演化后不一致。
    assert "def is_conflicting_binary(destination: str, source: str) -> bool:" in spec
    assert "if not is_conflicting_binary(destination, source)" in spec
    assert "analysis.binaries = TOC(" in spec
    assert "if not is_conflicting_binary(entry[0], entry[1])" in spec


def test_release_bundle_excludes_root_level_icu_runtime_conflicts() -> None:
    """发布根层不能出现 ICU 运行库，否则 Qt 会加载到 ABI 不匹配的版本。

    回归背景：开发机的 Poppler 运行时被递归依赖分析带入发布包后，
    `_internal\\icuuc.dll` 会先于 `PySide6` 子目录被加载，
    安装版启动时直接报
    `DLL load failed while importing QtWidgets: 找不到指定的程序。`
    """

    spec = (PROJECT_ROOT / "ZeroCaption.spec").read_text(encoding="utf-8-sig")

    assert 'name.startswith("icu")' in spec
    assert 'name.endswith(".dll")' in spec
    assert "bundled_at_root = len(Path(destination).parts) == 1" in spec


def test_installer_clears_stale_payload_before_copying_new_files() -> None:
    """升级安装必须先清掉旧发布载荷目录，避免旧版本残留 DLL 继续生效。

    回归背景：`[Files]` 只覆盖新清单里的文件，不删除“新版本已不再携带”的
    旧文件。旧版本根层的 `icuuc.dll` 等残留会让升级后的程序一启动就崩溃。
    """

    manifest = (PROJECT_ROOT / "installer" / "ZeroCaption.iss").read_text(
        encoding="utf-8-sig"
    )

    install_delete = manifest.index("[InstallDelete]")
    files_section = manifest.index("[Files]")
    # Inno Setup 总是先处理 `[InstallDelete]` 再处理 `[Files]`，文本顺序不影响行为；
    # 这里仍然断言它写在前面，是为了让人阅读时能直接看出“先清理旧载荷再复制”。
    assert install_delete < files_section
    assert 'Type: filesandordirs; Name: "{app}\\_internal"' in manifest


def test_application_logo_is_used_by_executable_and_installer() -> None:
    """桌面程序与安装器应使用同一份多尺寸 Windows 图标。"""

    icon_path = PROJECT_ROOT / "resources" / "icons" / "zero-caption.ico"
    logo_path = PROJECT_ROOT / "resources" / "icons" / "zero-caption-logo.png"
    spec = (PROJECT_ROOT / "ZeroCaption.spec").read_text(encoding="utf-8-sig")
    manifest = (PROJECT_ROOT / "installer" / "ZeroCaption.iss").read_text(
        encoding="utf-8-sig"
    )

    assert icon_path.is_file()
    assert logo_path.is_file()
    assert '"resources" / "icons" / "zero-caption.ico"' in spec
    assert "SetupIconFile=..\\resources\\icons\\zero-caption.ico" in manifest
