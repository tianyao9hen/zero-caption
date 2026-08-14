"""媒体处理抽象端口。

这个模块属于核心层，只描述识别流程需要哪些媒体能力。
具体怎样调用 `FFmpeg` 或 `ffprobe` 由基础设施层决定，
核心用例不应该拼接命令行或解析第三方工具输出。
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from core.dto.media_dto import MediaProbeResultDTO


class MediaProbe(Protocol):
    """读取本地媒体基础信息的能力。"""

    def probe(self, source_path: Path) -> MediaProbeResultDTO:
        """读取媒体时长、视频流和音频流信息。"""

        ...


class AudioExtractor(Protocol):
    """把视频音轨抽取为独立音频文件的能力。"""

    def extract_audio(self, source_path: Path, output_path: Path) -> Path:
        """从源视频抽取音频，并返回实际生成的文件路径。"""

        ...
