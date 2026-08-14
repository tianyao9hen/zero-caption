"""翻译批次构造器单元测试。

测试保护单次请求的条数和字符数边界，以及批次拆分后字幕顺序不变。
"""

from __future__ import annotations

from core.dto.subtitle_dto import SubtitleSegmentDTO
from infrastructure.translation.batch_builder import TranslationBatchBuilder


def _segment(segment_id: str, text: str) -> SubtitleSegmentDTO:
    """构造只关注编号和正文的字幕片段。"""

    return SubtitleSegmentDTO(
        segment_id=segment_id,
        start_ms=0,
        end_ms=1_000,
        text=text,
        language="ja-JP",
    )


def test_batch_builder_splits_by_count_and_preserves_order() -> None:
    """超过条数上限时应拆批，并保持每批及整体的原始顺序。"""

    # arrange：三条字幕配合两条上限，能明确观察一次拆分。
    builder = TranslationBatchBuilder(max_segments=2, max_characters=100)
    segments = [_segment("seg-1", "一"), _segment("seg-2", "二"), _segment("seg-3", "三")]

    # act
    batches = builder.build_batches(segments, "ja-JP", "zh-CN")

    # assert
    assert [batch.segment_ids for batch in batches] == [
        ("seg-1", "seg-2"),
        ("seg-3",),
    ]


def test_batch_builder_splits_by_text_characters() -> None:
    """累计正文超过字符上限时应在当前字幕之前开始新批次。"""

    # arrange：每条正文两字符，字符上限为三，第二条不能和第一条同批。
    builder = TranslationBatchBuilder(max_segments=10, max_characters=3)
    segments = [_segment("seg-1", "甲乙"), _segment("seg-2", "丙丁")]

    # act
    batches = builder.build_batches(segments, "ja-JP", "zh-CN", context="作品上下文")

    # assert：上下文属于批次元数据，不会改变字幕分组。
    assert [batch.segment_ids for batch in batches] == [("seg-1",), ("seg-2",)]
    assert all(batch.context == "作品上下文" for batch in batches)
