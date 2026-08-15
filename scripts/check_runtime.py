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

from config.paths import resource_path
from config.settings import Settings, load_settings
from infrastructure.asr.hardware_probe import CTranslate2HardwareProbe


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

    # 第一步：检查媒体工具。绝对路径和随包资源优先，开发环境再回退到 PATH。
    ffmpeg_path = _find_executable(settings.runtime.ffmpeg_path)
    items.append(
        ProbeItem(
            name="ffmpeg",
            status="pass" if ffmpeg_path else "fail",
            message=ffmpeg_path or "未找到 `ffmpeg`，后续媒体处理前需要先安装。",
        )
    )

    ffprobe_path = _find_executable(settings.runtime.ffprobe_path)
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
    # 这里只检查地址、模型和密钥是否齐全，不会访问网络或验证密钥真值。
    translation_ready = settings.engine.translation.is_configured()
    items.append(
        ProbeItem(
            name="translation_config",
            status="pass" if translation_ready else "warn",
            message="翻译配置完整。"
            if translation_ready
            else "尚未配置翻译接口地址、模型名或 API 密钥，完整翻译主链路暂不可运行。",
        )
    )

    # 第四步：检查发布清单中的每个 ASR 模型是否已经完整准备。
    model_directories = {
        model_name: _resolve_asr_model_dir(model_name)
        for model_name in settings.engine.asr.bundled_models
    }
    missing_models = [
        model_name
        for model_name, model_dir in model_directories.items()
        if model_dir is None
        or not all(
            (model_dir / name).is_file()
            for name in ("config.json", "model.bin", "tokenizer.json")
        )
    ]
    model_ready = not missing_models
    items.append(
        ProbeItem(
            name="asr_model",
            status="pass" if model_ready else "warn",
            message=(
                "已检测到内置 ASR 模型："
                + "、".join(settings.engine.asr.bundled_models)
                if model_ready
                else "缺少内置 ASR 模型：" + "、".join(missing_models)
            ),
        )
    )

    # 第五步：展示真实硬件结论。CPU 是有效回退，因此没有 CUDA 也不阻断启动。
    hardware_info = CTranslate2HardwareProbe().probe()
    items.append(
        ProbeItem(
            name="asr_hardware",
            status="pass",
            message=hardware_info.diagnostic_message,
        )
    )

    # 第六步：检查模型缓存目录是否可用。
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


def _find_executable(value: str) -> str | None:
    """解析绝对路径、应用资源路径和 PATH 中的媒体工具。"""

    configured = Path(value)
    candidates = [configured] if configured.is_absolute() else [resource_path(configured)]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return shutil.which(value)


def _resolve_asr_model_dir(model_name: str) -> Path | None:
    """返回已配置或随程序发布的 ASR 模型目录。"""

    configured = Path(model_name)
    if configured.is_absolute() and configured.is_dir():
        return configured
    bundled = resource_path(Path("resources/models") / model_name)
    return bundled if bundled.is_dir() else None


def main() -> int:
    """运行默认配置下的探针，并把结果打印到控制台。"""

    settings = load_settings()
    report = probe_runtime(settings=settings, workspace_root=Path("."))

    for item in report.items:
        print(f"[{item.status.upper()}] {item.name}: {item.message}")

    return 0 if report.status != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
