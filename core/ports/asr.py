"""ASR 抽象端口定义模块。

端口用于描述 core 层需要什么能力，但不绑定具体实现。
真正的适配器实现应该放在 infrastructure 层。
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from core.dto.asr_dto import AsrHardwareInfoDTO
from core.dto.subtitle_dto import SubtitleSegmentDTO


@runtime_checkable
class AsrEngine(Protocol):
    """核心流程所需的语音转文本能力。

    这个端口只关心“给我音频路径，我返回带时间轴的字幕片段”。
    它不规定具体模型，也不要求调用方知道底层是本地推理还是别的实现。
    """

    def transcribe(
        self,
        audio_path: Path,
        language: str | None = None,
    ) -> list[SubtitleSegmentDTO]: ...


@runtime_checkable
class AsrCapabilityProbe(Protocol):
    """应用层所需的本地识别硬件探测能力。

    核心层只约定返回结构化快照，不关心探测是通过 `CTranslate2`、
    驱动命令还是未来的其他实现完成。
    """

    def probe(self) -> AsrHardwareInfoDTO: ...


@runtime_checkable
class AsrRuntimeReporter(Protocol):
    """识别适配器可选的实际运行参数报告能力。"""

    def runtime_summary(self) -> str:
        """返回适合任务页展示的模型、设备、精度或回退摘要。"""

        ...


@runtime_checkable
class AsrRuntimeVerifier(Protocol):
    """发布验收可选的真实推理探针能力。"""

    def verify_runtime(
        self,
        audio_path: Path,
        language: str | None = None,
    ) -> str:
        """强制执行一次模型计算，并返回实际模型、设备和精度摘要。"""

        ...
