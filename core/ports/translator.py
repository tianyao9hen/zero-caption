"""翻译能力抽象端口定义模块。"""

from __future__ import annotations

from typing import Protocol


class Translator(Protocol):
    """字幕处理流程所需的翻译能力。"""

    def translate(self, text: str, source_lang: str, target_lang: str): ...
