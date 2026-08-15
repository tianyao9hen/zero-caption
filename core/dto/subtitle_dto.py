"""字幕相关 DTO 模块。

阶段 1 先把字幕片段、识别输入输出和翻译输入输出表达成稳定对象，
避免后续在层之间传递裸字典或随手拼出来的结构。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.domain.entities import Task
from core.dto.media_dto import MediaProbeResultDTO


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
    """描述识别用例的输入参数。

    `audio_path` 主要用于测试、恢复任务或调用方已经准备好音频的场景。
    常规主链路只传项目编号，识别用例会根据项目记录自行探测并抽取音频。
    """

    project_id: str
    audio_path: Path | None = None
    language: str | None = None


@dataclass(slots=True)
class TranscribeVideoResult:
    """描述识别用例的输出结果。

    除字幕片段外，结果还会返回本次使用的音频、字幕文件和媒体信息，
    方便命令行入口、后续 UI 和恢复逻辑明确知道产物落在哪里。
    """

    project_id: str
    task: Task
    source_segments: list[SubtitleSegmentDTO]
    audio_path: Path | None = None
    subtitle_path: Path | None = None
    media: MediaProbeResultDTO | None = None
    reused_audio: bool = False
    reused_transcript: bool = False
    runtime_message: str = ""


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
    subtitle_path: Path | None = None
    reused_translation: bool = False


@dataclass(frozen=True, slots=True)
class TranslationProgressDTO:
    """描述一条字幕刚刚完成翻译时的实时展示数据。

    这个 DTO 只携带字幕文本和序号，不包含媒体路径、密钥或网络请求信息。
    `frozen=True` 表示事件创建后不可修改，避免后台线程发布后内容又发生变化。
    """

    task_id: str
    current_index: int
    total_segments: int
    source_text: str
    translated_text: str
