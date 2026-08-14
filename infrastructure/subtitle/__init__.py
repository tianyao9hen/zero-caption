"""字幕后处理基础设施包。

这个包属于 `infrastructure` 层，负责把 ASR 已经产出的字幕片段
整理成可以落盘的字幕文件格式。这里不调用 UI、不访问数据库，
也不处理翻译字幕，避免阶段 2 的原文字幕链路和后续阶段混在一起。
"""

from infrastructure.subtitle.aligner import SubtitleAligner
from infrastructure.subtitle.formatter import SubtitleFormatter
from infrastructure.subtitle.srt_writer import SrtWriter

__all__ = [
    "SubtitleAligner",
    "SubtitleFormatter",
    "SrtWriter",
]
