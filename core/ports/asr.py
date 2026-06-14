"""ASR 抽象端口定义模块。

端口用于描述 core 层需要什么能力，但不绑定具体实现。
真正的适配器实现应该放在 infrastructure 层。
"""

from __future__ import annotations

from typing import Protocol


class AsrEngine(Protocol):
    """核心流程所需的语音转文本能力。"""

    def transcribe(self, audio_path: str, language: str | None = None): ...
