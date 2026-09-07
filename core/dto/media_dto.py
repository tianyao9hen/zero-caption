"""媒体探测相关 DTO 模块。

阶段 2 先把媒体基础信息的结构稳定下来，
这样后续 `ffprobe` 适配器和识别主链路之间就不需要传递裸字典。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AudioSegmentRangeDTO:
    """表示长音频中一个需要独立处理的绝对时间范围。

    `frozen=True` 表示范围创建后不可修改，避免后台识别过程中意外改变
    起止位置；毫秒单位和字幕 DTO 保持一致，便于识别结果回填时间偏移。
    """

    start_ms: int
    end_ms: int


@dataclass(slots=True)
class AudioStreamDTO:
    """表示媒体中的一条音频流基础信息。"""

    codec_name: str
    sample_rate: int
    channels: int
    language: str | None = None


@dataclass(slots=True)
class VideoStreamDTO:
    """表示媒体中的主视频流基础信息。"""

    codec_name: str
    width: int
    height: int


@dataclass(slots=True)
class MediaProbeResultDTO:
    """表示一次媒体探测的结构化结果。"""

    source_path: Path
    duration_ms: int
    video_stream: VideoStreamDTO | None
    audio_streams: list[AudioStreamDTO]
