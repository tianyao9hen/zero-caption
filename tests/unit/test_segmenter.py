"""音频切块组件单元测试。

这组测试先把阶段 2 需要的切块行为固定下来：
1. 支持固定时长切块。
2. 支持相邻片段保留少量重叠。
3. 每段结果都必须保留相对于原始音频的时间偏移。
"""

from __future__ import annotations

from infrastructure.media.segmenter import AudioSegmenter


def _segment_ranges(segments: list[object]) -> list[tuple[int, int]]:
    """把切块结果转成更容易断言的起止时间列表。"""

    return [(segment.start_ms, segment.end_ms) for segment in segments]


def test_audio_segmenter_splits_audio_into_fixed_duration_ranges():
    """固定时长切块时，最后一段应保留原始音频的尾部偏移。"""

    # arrange：这里故意让总时长不能被整除，
    # 这样测试可以保护“最后一段不要被截掉”这个行为。
    segmenter = AudioSegmenter(chunk_duration_ms=300_000, overlap_ms=0)

    # act：当前任务只要求先固定切块计划，
    # 所以这里先约定由 `plan_segments` 返回纯时间范围结果。
    segments = segmenter.plan_segments(total_duration_ms=610_000)

    # assert：每段的时间都应是相对于原始音频的绝对偏移，
    # 而不是重新从 0 开始编号。
    assert _segment_ranges(segments) == [
        (0, 300_000),
        (300_000, 600_000),
        (600_000, 610_000),
    ]


def test_audio_segmenter_keeps_small_overlap_between_neighbor_ranges():
    """重叠切块时，相邻片段应共享边界时间，但仍保留原始偏移。"""

    # arrange：15 秒重叠是设计文档里提到的“少量重叠”最小化表达，
    # 足够保护句子边界，又不会把整段范围写得太复杂。
    overlap_ms = 15_000
    segmenter = AudioSegmenter(chunk_duration_ms=300_000, overlap_ms=overlap_ms)

    # act
    segments = segmenter.plan_segments(total_duration_ms=620_000)

    # assert：除了精确校验每段起止时间，还要单独说明重叠关系，
    # 这样后续实现若把重叠量算错，失败信息会更直接。
    assert _segment_ranges(segments) == [
        (0, 300_000),
        (285_000, 585_000),
        (570_000, 620_000),
    ]
    assert segments[0].end_ms - segments[1].start_ms == overlap_ms
    assert segments[1].end_ms - segments[2].start_ms == overlap_ms
