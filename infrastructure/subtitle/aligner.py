"""字幕时间轴规整组件。

这个模块只处理字幕片段的时间范围：排序、截断负数起点、消除相邻重叠。
它不负责文字清理，也不写出 `SRT` 文件；这些职责分别由 formatter
和 writer 组件承担。
"""

from __future__ import annotations

from dataclasses import replace

from core.dto.subtitle_dto import SubtitleSegmentDTO


class SubtitleAligner:
    """把字幕片段规整成可写入 `SRT` 的基础时间轴。

    多个音频块的 ASR 结果合并后，可能出现轻微乱序或边界重叠。
    这个类提供最小的稳定规则，让后续 `SRT` 写出不会产生非法时间范围。
    """

    def __init__(self, min_duration_ms: int = 1) -> None:
        """初始化时间轴规整器。

        参数：
            min_duration_ms：当片段结束时间早于规整后的开始时间时，
            用这个最小时长兜底，避免出现结束时间小于开始时间的字幕。
        """

        if min_duration_ms <= 0:
            raise ValueError("字幕最小时长必须大于 0。")

        self.min_duration_ms = min_duration_ms

    def normalize_timeline(
        self,
        segments: list[SubtitleSegmentDTO],
    ) -> list[SubtitleSegmentDTO]:
        """返回排序且不重叠的字幕片段列表。

        参数：
            segments：待规整的字幕片段列表。

        返回：
            新的字幕片段列表。方法不会原地修改输入对象，
            这样调用方仍然可以保留原始 ASR 结果用于调试或缓存。
        """

        normalized: list[SubtitleSegmentDTO] = []
        previous_end_ms = 0

        # 第一步：先按开始时间排序。结束时间和片段编号只是并列时的稳定排序键，
        # 可以让同一批输入在多次运行时得到一致顺序。
        sorted_segments = sorted(
            segments,
            key=lambda segment: (
                max(0, segment.start_ms),
                max(0, segment.end_ms),
                segment.segment_id,
            ),
        )

        # 第二步：逐段规整时间范围。每一条的开始时间不能小于 0，
        # 也不能早于上一条已经确定的结束时间。
        for segment in sorted_segments:
            start_ms = max(0, segment.start_ms)
            start_ms = max(start_ms, previous_end_ms)
            end_ms = max(start_ms + self.min_duration_ms, segment.end_ms)

            normalized_segment = replace(
                segment,
                start_ms=start_ms,
                end_ms=end_ms,
            )
            normalized.append(normalized_segment)
            previous_end_ms = normalized_segment.end_ms

        return normalized
