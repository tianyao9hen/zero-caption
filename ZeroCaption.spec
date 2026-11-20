# -*- mode: python ; coding: utf-8 -*-

"""PyInstaller 便携式 Windows 发布包配置。"""

from pathlib import Path
import tomllib

from PyInstaller.building.datastruct import TOC
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

# 某些开发运行时会让 `av` 的递归依赖分析找到外部 `libheif` 目录，
# 并把它自带的 VC 运行库平铺到 `_internal` 根目录。PySide6/shiboken6
# 已经携带匹配版本；根目录的另一版本会因 Windows DLL 搜索顺序抢先加载，
# 导致 `QtWidgets` 导入失败。
#
# 同样，当前开发机的 Poppler 运行时可能被 `PyInstaller` 递归分析带入，
# 其中的 `icuuc.dll` / `icudt78.dll` 与 Qt 使用的 ICU ABI 不兼容。Qt 的
# `Qt6Core.dll` 需要系统或 PySide6 配套的 ICU 导出符号，不能让 Poppler
# 的带版本后缀符号抢先进入发布目录。因此按来源目录统一排除这两类外部 DLL，
# 并额外按“发布目录根层 + `icu` 开头文件名”兜底，防止其他来源再带入同名文件。
# 保留 VC 运行库名称清单，便于发布契约测试明确记录历史冲突类型；
# 实际过滤按来源目录完成，因为同名 DLL 也可能来自 Qt 自带目录。
conflicting_vc_runtimes = {
    "vcruntime140.dll",
    "msvcp140.dll",
    "vcruntime140_1.dll",
}
conflicting_external_parts = {"libheif", "poppler"}


def is_conflicting_binary(destination: str, source: str) -> bool:
    """判断一个待收集文件是否会破坏 Qt 运行库的加载。

    返回 `True` 表示该文件必须从发布包中剔除。这里刻意写成独立函数，
    让 `binaries` 列表和 `Analysis` 之后的二次清理共用同一套判断，
    避免两处规则各写一遍后逐渐走形。
    """

    # 条件一：来自外部 `libheif` / `Poppler` 目录的文件一律剔除。
    # 这些目录来自开发机额外的运行时缓存，并不是本应用的依赖，
    # 却会被 `PyInstaller` 的递归依赖分析顺带收集进发布目录。
    if any(part.casefold() in conflicting_external_parts for part in Path(source).parts):
        return True

    # 条件二：发布目录根层的 ICU 运行库同样剔除。
    # Qt 的 `Qt6Core.dll` 会按文件名去加载 `icuuc.dll`，而 Poppler 等第三方
    # 产品自带的 ICU 版本与导出符号都不同。根层 DLL 会先于 `PySide6`
    # 子目录被 Windows 加载，一旦抢到就是
    # `DLL load failed while importing QtWidgets: 找不到指定的程序。`
    name = Path(destination).name.casefold()
    bundled_at_root = len(Path(destination).parts) == 1
    return bundled_at_root and name.startswith("icu") and name.endswith(".dll")


binaries = [
    (destination, source)
    for destination, source in binaries
    if not is_conflicting_binary(destination, source)
]

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
    runtime_hooks=[str(repo_root / "pyi_rth_qt_dlls.py")],
    excludes=[],
    noarchive=False,
)
# `Analysis` 还会自动递归扫描扩展模块的 DLL 依赖；这些结果不经过上面的
# `binaries` 列表，因此要在分析完成后再次清理，确保外部 `libheif` 的
# 根级 VC 运行库不会覆盖 Qt 运行时。
analysis.binaries = TOC(
    # `TOC` 条目是 `(目标路径, 来源路径, 类型)` 三元组，前两项与上面的
    # `binaries` 列表含义一致，所以可以直接复用同一个判断函数。
    entry
    for entry in analysis.binaries
    if not is_conflicting_binary(entry[0], entry[1])
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
