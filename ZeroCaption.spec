# -*- mode: python ; coding: utf-8 -*-

"""PyInstaller 便携式 Windows 发布包配置。"""

from pathlib import Path
import tomllib

from PyInstaller.utils.hooks import collect_all


repo_root = Path.cwd().resolve()
# 构建配置直接读取应用默认模型，保证校验脚本、运行时配置和打包资源始终使用同一名称。
with (repo_root / "config" / "default.toml").open("rb") as config_file:
    default_model = tomllib.load(config_file)["engine"]["asr"]["model_name"]

# 第一步：收集会通过动态库或运行时导入加载的本地识别依赖。
# 这些包不能只依赖静态导入分析，否则安装版可能在真正识别时才缺少 DLL。
# 只把运行时真正需要的资源加入安装包。
# 模型目录可能同时存在多个本地版本，若直接打包整个 `resources`，会把未选中的模型也复制进去，
# 既增加安装包体积，又让用户误以为程序会自动使用它们。
datas: list[tuple[str, str]] = [
    (str(repo_root / "config" / "default.toml"), "config"),
    (str(repo_root / "resources" / "bin"), "resources/bin"),
    (str(repo_root / "resources" / "icons"), "resources/icons"),
    (str(repo_root / "resources" / "themes"), "resources/themes"),
    (
        str(repo_root / "resources" / "models" / default_model),
        f"resources/models/{default_model}",
    ),
]
binaries: list[tuple[str, str]] = []
hiddenimports: list[str] = []
for package_name in (
    "faster_whisper",
    "ctranslate2",
    "tokenizers",
    "huggingface_hub",
    "onnxruntime",
    "av",
):
    package_datas, package_binaries, package_hiddenimports = collect_all(package_name)
    datas.extend(package_datas)
    binaries.extend(package_binaries)
    hiddenimports.extend(package_hiddenimports)


analysis = Analysis(
    [str(repo_root / "app" / "main.py")],
    pathex=[str(repo_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="ZeroCaption",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="ZeroCaption",
)
