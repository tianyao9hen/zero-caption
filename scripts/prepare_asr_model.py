"""准备随 Windows 发布包携带的 `faster-whisper` 模型。

这个脚本属于发布工具层，职责是把 Hugging Face 上的 CTranslate2 模型下载到
`resources/models`。它不参与应用运行时逻辑；发布包若缺少模型会在构建前直接失败，
避免用户安装后才发现本地识别依赖网络下载。
"""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    # 直接运行脚本时，解释器默认只把 `scripts` 放入导入路径。
    # 把仓库根目录加入路径，才能复用配置层的资源路径解析。
    sys.path.insert(0, str(PROJECT_ROOT))

from config.paths import resource_path
from config.settings import load_settings


REQUIRED_MODEL_FILES = ("config.json", "model.bin", "tokenizer.json")
MODELSCOPE_MODEL_FILES = (
    "config.json",
    "configuration.json",
    "model.bin",
    "tokenizer.json",
    "vocabulary.txt",
)


def model_is_ready(model_dir: Path) -> bool:
    """判断模型目录是否包含运行时加载所需的最小文件集合。"""

    return model_dir.is_dir() and all(
        (model_dir / filename).is_file()
        and (model_dir / filename).stat().st_size > 0
        for filename in REQUIRED_MODEL_FILES
    )


def _download_from_modelscope(model_name: str, target: Path) -> None:
    """从 ModelScope 镜像流式下载模型文件。

    该路径只在 Hugging Face 下载失败时启用。每个文件先写入 `.part` 临时文件，
    完整下载后再原子替换正式文件，避免网络中断留下看似完整、实际损坏的模型。
    """

    base_url = (
        "https://www.modelscope.cn/models/Systran/"
        f"faster-whisper-{model_name}/resolve/master"
    )
    target.mkdir(parents=True, exist_ok=True)

    for filename in MODELSCOPE_MODEL_FILES:
        output_path = target / filename
        temporary_path = output_path.with_suffix(f"{output_path.suffix}.part")
        request = Request(
            f"{base_url}/{filename}",
            headers={"User-Agent": "ZeroCaption-model-preparer/1.0"},
        )
        print(f"从 ModelScope 下载：{filename}")
        try:
            with urlopen(request, timeout=120) as response:
                with temporary_path.open("wb") as output:
                    # `copyfileobj` 按块传输数据，不会把数百兆模型一次性读入内存。
                    shutil.copyfileobj(response, output, length=1024 * 1024)
            temporary_path.replace(output_path)
        finally:
            temporary_path.unlink(missing_ok=True)


def prepare_model(model_name: str, output_root: Path) -> Path:
    """下载或复用指定模型，并返回最终模型目录。"""

    if Path(model_name).is_absolute() or "/" in model_name or "\\" in model_name:
        raise ValueError("发布包模型名应使用 tiny、base、small 等标准名称。")

    target = output_root / model_name
    if model_is_ready(target):
        print(f"复用已准备的 ASR 模型：{target}")
        return target

    try:
        from huggingface_hub import snapshot_download
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "当前构建环境缺少 `huggingface-hub`，请先安装项目运行依赖。"
        ) from exc

    # `faster-whisper` 官方模型仓库采用固定命名规则，
    # 下载整个仓库可以避免遗漏词表或预处理配置文件。
    repository = f"Systran/faster-whisper-{model_name}"
    output_root.mkdir(parents=True, exist_ok=True)
    print(f"开始下载 ASR 模型：{repository}")
    try:
        snapshot_download(repo_id=repository, local_dir=target)
    except Exception as exc:
        # 国内网络环境可能无法连接 Hugging Face。构建工具在这里回退到 ModelScope，
        # 下载内容仍是同名的 Systran CTranslate2 模型，不改变应用运行时行为。
        print(f"Hugging Face 下载失败，改用 ModelScope：{exc}")
        _download_from_modelscope(model_name=model_name, target=target)

    if not model_is_ready(target):
        raise RuntimeError(f"模型下载完成但缺少必要文件：{target}")
    print(f"ASR 模型准备完成：{target}")
    return target


def main() -> int:
    """读取发布模型清单，并逐个准备到只读资源目录。"""

    parser = argparse.ArgumentParser(description="准备 Zero Caption 内置 ASR 模型")
    parser.add_argument(
        "--model",
        action="append",
        default=None,
        help="只准备指定模型；可重复传入。不传时准备默认清单中的全部模型。",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=resource_path("resources/models"),
        help="模型输出根目录。",
    )
    args = parser.parse_args()

    default_settings = load_settings(resource_path("config/default.toml"))
    model_names = args.model or list(default_settings.engine.asr.bundled_models)
    for model_name in model_names:
        prepare_model(model_name=model_name, output_root=args.output_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
