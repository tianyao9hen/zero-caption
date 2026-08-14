"""字幕后处理与写出抽象端口。

核心用例通过这些端口组织去重、时间轴规整和字幕落盘，
但不依赖 `infrastructure.subtitle` 下的具体类。
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from core.dto.subtitle_dto import SubtitleSegmentDTO


class SubtitleFormatterPort(Protocol):
    """清理字幕文本和明显重复片段的能力。"""

    def remove_duplicates(
        self,
        segments: list[SubtitleSegmentDTO],
    ) -> list[SubtitleSegmentDTO]:
        """返回移除明显边界重复后的字幕片段。"""

        ...


class SubtitleAlignerPort(Protocol):
    """规整字幕时间轴的能力。"""

    def normalize_timeline(
        self,
        segments: list[SubtitleSegmentDTO],
    ) -> list[SubtitleSegmentDTO]:
        """返回排序且时间范围合法的字幕片段。"""

        ...


class SubtitleWriter(Protocol):
    """把字幕片段写入正式字幕文件的能力。"""

    def write_file(
        self,
        segments: list[SubtitleSegmentDTO],
        output_path: str | Path,
    ) -> Path:
        """写出字幕文件，并返回实际生成的文件路径。"""

        ...
