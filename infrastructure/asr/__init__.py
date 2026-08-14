"""本地 ASR 适配器导出模块。

这个包属于 infrastructure 层，负责承载语音识别引擎的具体实现。
core 层只依赖 `AsrEngine` 端口，不应该知道这里使用的是哪一个第三方库。
"""

from infrastructure.asr.faster_whisper_engine import FasterWhisperEngine

__all__ = ["FasterWhisperEngine"]
