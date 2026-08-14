"""`faster-whisper` 适配器集成测试。

这组测试属于基础设施层的集成测试，职责只有一个：
验证本地 ASR 适配器能把真实音频识别成 `core` 层约定的字幕片段 DTO。
"""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
import logging
import shutil
import uuid

import pytest

from app.container import AppContainer
from config.settings import Settings
from core.dto.subtitle_dto import SubtitleSegmentDTO
from core.ports.asr import AsrEngine
from infrastructure.media.ffmpeg import FFmpegAdapter
from infrastructure.storage.workspace import WorkspaceManager


def _load_engine_class() -> type[object]:
    """加载未来要实现的 `faster-whisper` 适配器类。

    这里不在模块顶层直接 import，
    是为了让当前阶段的失败信息更清楚：
    与其让测试在收集阶段抛出难懂的导入错误，
    不如明确告诉实现者现在缺的是哪一个模块和类。
    """

    try:
        module = import_module("infrastructure.asr.faster_whisper_engine")
    except ModuleNotFoundError as exc:
        pytest.fail(
            "当前缺少真实 ASR 实现：请新增 "
            "`infrastructure.asr.faster_whisper_engine` 模块，"
            "并在其中提供 `FasterWhisperEngine` 适配器类。"
        )

    engine_class = getattr(module, "FasterWhisperEngine", None)
    if engine_class is None:
        pytest.fail(
            "当前缺少真实 ASR 实现："
            "`infrastructure.asr.faster_whisper_engine` 中应定义 "
            "`FasterWhisperEngine` 类。"
        )

    return engine_class


def _extract_demo_audio(tmp_path: Path) -> Path:
    """把仓库里的短视频样例转成测试所需的音频文件。

    阶段 2 已经先落了 `FFmpegAdapter`，
    这里复用它生成临时 `wav`，避免为了这一次测试额外提交二进制音频样例。
    """

    source_path = Path("tests/video/demo.mp4")
    output_path = tmp_path / "demo.wav"

    assert source_path.exists(), "缺少阶段 2 约定的短视频样例 `tests/video/demo.mp4`。"

    adapter = FFmpegAdapter()
    return adapter.extract_audio(source_path=source_path, output_path=output_path)


@pytest.fixture()
def workspace_temp_dir() -> Path:
    """在仓库工作区内创建临时目录，避开受限系统临时目录。"""

    temp_dir = Path(".tmp") / "tests" / f"faster-whisper-{uuid.uuid4().hex}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_faster_whisper_engine_returns_subtitle_segment_dto_list(workspace_temp_dir: Path) -> None:
    """应当返回包含文本和时间轴的 `SubtitleSegmentDTO` 列表。"""

    # arrange：先准备真实音频输入，再加载未来要补齐的 ASR 适配器类。
    engine_class = _load_engine_class()
    audio_path = _extract_demo_audio(workspace_temp_dir)

    # 模型文件体积较大，测试缓存放在 `.tmp` 这个已忽略目录下。
    # 这样第一次下载后可以复用，避免每次运行都重新访问模型仓库。
    model_cache_dir = Path(".tmp") / "models" / "faster-whisper"
    engine = engine_class(
        model_name="tiny",
        model_cache_dir=model_cache_dir,
    )

    # act：识别结果必须直接面向 `core` 层约定的 DTO，
    # 不能返回裸字典、元组或第三方库原始对象。
    segments = engine.transcribe(audio_path=audio_path, language=None)

    # assert：阶段 2 的 ASR 输出至少要包含“文本 + 起止时间轴”。
    assert isinstance(segments, list)
    assert segments, "ASR 适配器应返回至少一个字幕片段，当前说明真实识别结果还未接通。"
    assert all(isinstance(segment, SubtitleSegmentDTO) for segment in segments)

    first_segment = segments[0]
    assert first_segment.text.strip(), "字幕片段必须包含非空文本。"
    assert first_segment.start_ms >= 0
    assert first_segment.end_ms > first_segment.start_ms


def test_container_can_create_real_asr_engine() -> None:
    """容器应当能装配出符合 `AsrEngine` 端口的真实实现。"""

    # arrange：这里不直接跑识别，只验证 app 层是否已经完成
    # “配置 -> 具体适配器”的装配职责。
    container = AppContainer(
        settings=Settings(),
        workspace=WorkspaceManager(Path("data")),
        logger=logging.getLogger("test"),
    )

    # act：从容器中拿到当前阶段约定的本地 ASR 实现。
    engine = container.create_asr_engine()

    # assert：返回对象至少应满足 `AsrEngine` 端口要求，
    # 并且暴露出真实适配器类名，方便后续用例直接复用。
    assert isinstance(engine, AsrEngine)
    assert engine.__class__.__name__ == "FasterWhisperEngine"
