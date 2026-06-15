"""翻译能力抽象端口定义模块。"""

from __future__ import annotations

from typing import Protocol

from core.dto.subtitle_dto import SubtitleSegmentDTO


class Translator(Protocol):
    """字幕处理流程所需的翻译能力。

    这里刻意只接收字幕片段和语言信息，不接收原始媒体文件路径，
    用来守住“云端只传字幕文本”的架构边界。
    """

    def translate_segments(
        self,
        segments: list[SubtitleSegmentDTO],
        source_language: str,
        target_language: str,
        context: str | None = None,
    ) -> list[SubtitleSegmentDTO]: ...
