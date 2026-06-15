"""ASR 抽象端口定义模块。

端口用于描述 core 层需要什么能力，但不绑定具体实现。
真正的适配器实现应该放在 infrastructure 层。
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from core.dto.subtitle_dto import SubtitleSegmentDTO


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
