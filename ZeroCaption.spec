# -*- mode: python ; coding: utf-8 -*-

"""PyInstaller 便携式 Windows 发布包配置。"""

from pathlib import Path
import tomllib

from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs


repo_root = Path.cwd().resolve()
# 构建配置直接读取应用发布模型清单，保证校验脚本、运行时和打包资源一致。
with (repo_root / "config" / "default.toml").open("rb") as config_file:
    bundled_models = tomllib.load(config_file)["engine"]["asr"]["bundled_models"]

# 第一步：收集会通过动态库或运行时导入加载的本地识别依赖。
# 这些包不能只依赖静态导入分析，否则安装版可能在真正识别时才缺少 DLL。
# 只把运行时真正需要的资源加入安装包。
datas: list[tuple[str, str]] = [
    (str(repo_root / "config" / "default.toml"), "config"),
    (str(repo_root / "resources" / "bin"), "resources/bin"),
    (str(repo_root / "resources" / "icons"), "resources/icons"),
    (str(repo_root / "resources" / "themes"), "resources/themes"),
]
for model_name in bundled_models:
    datas.append(
        (
            str(repo_root / "resources" / "models" / model_name),
            f"resources/models/{model_name}",
        )
    )
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

# `CTranslate2` 在第一次真实 CUDA 运算时才加载 `cuBLAS`，静态分析无法发现。
# 保留 NVIDIA 包内原有的子目录，运行时辅助模块才能注册准确的 DLL 路径。
binaries.extend(collect_dynamic_libs("nvidia.cublas"))


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
    icon=str(repo_root / "resources" / "icons" / "zero-caption.ico"),
)
COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="ZeroCaption",
)
