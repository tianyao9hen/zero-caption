"""字幕相关 DTO 模块。

阶段 1 先把字幕片段、识别输入输出和翻译输入输出表达成稳定对象，
避免后续在层之间传递裸字典或随手拼出来的结构。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.domain.entities import Task


@dataclass(slots=True)
class SubtitleSegmentDTO:
    """表示一段带时间轴的字幕片段。"""

    segment_id: str
    start_ms: int
    end_ms: int
    text: str
    language: str


@dataclass(slots=True)
class TranscribeVideoInput:
    """描述识别用例的输入参数。"""

    project_id: str
    audio_path: Path
    language: str | None = None


@dataclass(slots=True)
class TranscribeVideoResult:
    """描述识别用例的输出结果。"""

    project_id: str
    task: Task
    source_segments: list[SubtitleSegmentDTO]


@dataclass(slots=True)
class TranslateSubtitlesInput:
    """描述翻译用例的输入参数。"""

    project_id: str
    source_language: str
    target_language: str
    context: str | None = None


@dataclass(slots=True)
class TranslateSubtitlesResult:
    """描述翻译用例的输出结果。"""

    project_id: str
    task: Task
    translated_segments: list[SubtitleSegmentDTO]
