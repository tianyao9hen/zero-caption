"""音频切块规划组件。

这个模块位于 `infrastructure/media`，职责很单一：
只根据总时长规划音频应该如何分段，不负责真正裁剪音频文件，
也不直接参与 ASR、字幕对齐或用例编排。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class AudioSegmentRange:
    """表示一段音频在原始时间轴上的起止范围。"""

    start_ms: int
    end_ms: int


class AudioSegmenter:
    """根据固定时长和重叠量规划长音频的切块范围。

    这个类只处理“时间怎么切”，不处理“文件怎么切”。
    后续即使底层用 `FFmpeg`、内存流或别的音频工具做真实裁剪，
    也可以复用这里产出的稳定时间范围。
    """

    def __init__(self, chunk_duration_ms: int, overlap_ms: int = 0) -> None:
        """初始化切块器。

        参数：
        - `chunk_duration_ms`：单段的目标时长，必须大于 0。
        - `overlap_ms`：相邻片段保留的重叠时长，必须大于等于 0，
          且不能大于等于单段时长，否则会导致切块起点无法向前推进。
        """

        if chunk_duration_ms <= 0:
            raise ValueError("切块时长必须大于 0。")
        if overlap_ms < 0:
            raise ValueError("重叠时长不能小于 0。")
        if overlap_ms >= chunk_duration_ms:
            raise ValueError("重叠时长必须小于切块时长。")

        self.chunk_duration_ms = chunk_duration_ms
        self.overlap_ms = overlap_ms

    def plan_segments(self, total_duration_ms: int) -> list[AudioSegmentRange]:
        """按原始时间轴规划音频切块范围。

        返回值中的每一段都保留原始音频的绝对时间偏移，
        这样后续 ASR 结果回填时，不需要再猜测这一段来自原始音频的哪里。
        """

        if total_duration_ms <= 0:
            return []

        segments: list[AudioSegmentRange] = []
        step_ms = self.chunk_duration_ms - self.overlap_ms
        start_ms = 0

        # 第一步：按“目标切块时长”生成当前片段。
        # 第二步：如果已经覆盖到音频尾部，就结束循环。
        # 第三步：否则按去掉重叠后的步长推进下一段起点。
        while start_ms < total_duration_ms:
            end_ms = min(start_ms + self.chunk_duration_ms, total_duration_ms)
            segments.append(AudioSegmentRange(start_ms=start_ms, end_ms=end_ms))

            if end_ms >= total_duration_ms:
                break

            start_ms += step_ms

        return segments
