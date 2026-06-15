"""阶段0运行时探针脚本。

这个文件属于脚本层，职责是把“当前机器是否具备后续开发条件”整理成一个
统一报告。它不负责自动安装依赖，只负责检查、归类和输出提示。
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import sys
from pathlib import Path
import shutil

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    # 直接用 `python scripts/check_runtime.py` 执行时，解释器默认只认识脚本目录。
    # 把仓库根目录放进 `sys.path`，脚本才可以稳定导入 `config`、`app` 这类包。
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import Settings, load_settings


@dataclass(slots=True)
class ProbeItem:
    """表示单项探针结果。"""

    name: str
    status: str
    message: str


@dataclass(slots=True)
class RuntimeReport:
    """表示一次完整运行时检查的汇总结果。"""

    status: str
    items: list[ProbeItem]


def probe_runtime(settings: Settings, workspace_root: Path) -> RuntimeReport:
    """检查运行时依赖、关键配置和缓存目录是否可用。

    参数：
        settings：已经解析好的结构化配置对象。
        workspace_root：用于解析相对缓存路径的基准目录。

    返回：
        一个 `RuntimeReport`，其中包含整体状态和逐项检查结果。
    """

    items: list[ProbeItem] = []

    # 第一步：检查命令行媒体工具是否可见。
    # `shutil.which` 是标准库提供的命令解析方式，适合先做最小环境探测。
    ffmpeg_path = shutil.which(settings.runtime.ffmpeg_path)
    items.append(
        ProbeItem(
            name="ffmpeg",
            status="pass" if ffmpeg_path else "fail",
            message=ffmpeg_path or "未找到 `ffmpeg`，后续媒体处理前需要先安装。",
        )
    )

    ffprobe_path = shutil.which(settings.runtime.ffprobe_path)
    items.append(
        ProbeItem(
            name="ffprobe",
            status="pass" if ffprobe_path else "fail",
            message=ffprobe_path or "未找到 `ffprobe`，媒体元数据探测暂不可用。",
        )
    )

    # 第二步：检查 Python 依赖是否已安装。
    # 这里先只探测 `faster_whisper` 是否能被解释器发现，不提前加载模型。
    whisper_spec = importlib.util.find_spec("faster_whisper")
    items.append(
        ProbeItem(
            name="faster_whisper",
            status="pass" if whisper_spec else "warn",
            message="已检测到 `faster-whisper`。"
            if whisper_spec
            else "未安装 `faster-whisper`，后续 ASR 阶段暂不可运行。",
        )
    )

    # 第三步：检查翻译配置是否达到最小可用状态。
    # 阶段0只要求知道“配置是否完整”，不在这里验证网络连通性或密钥真值。
    translation_ready = bool(
        settings.engine.translation.base_url and settings.engine.translation.model
    )
    items.append(
        ProbeItem(
            name="translation_config",
            status="pass" if translation_ready else "warn",
            message="翻译配置完整。"
            if translation_ready
            else "尚未配置翻译接口地址或模型名，阶段3前需要补齐。",
        )
    )

    # 第四步：检查模型缓存目录是否可用。
    # 这里显式创建目录，是为了提前暴露路径权限问题；后续模型下载阶段可以直接复用。
    cache_dir = workspace_root / settings.runtime.model_cache_dir
    cache_dir.mkdir(parents=True, exist_ok=True)
    items.append(
        ProbeItem(
            name="model_cache_dir",
            status="pass",
            message=f"模型缓存目录可用：{cache_dir}",
        )
    )

    overall = "pass"
    if any(item.status == "fail" for item in items):
        overall = "fail"
    elif any(item.status == "warn" for item in items):
        overall = "warn"

    return RuntimeReport(status=overall, items=items)


def main() -> int:
    """运行默认配置下的探针，并把结果打印到控制台。"""

    settings = load_settings()
    report = probe_runtime(settings=settings, workspace_root=Path("."))

    for item in report.items:
        print(f"[{item.status.upper()}] {item.name}: {item.message}")

    return 0 if report.status != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
