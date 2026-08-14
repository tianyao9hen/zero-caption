"""字幕时间轴规整组件单元测试。

这组测试只固定阶段 2 需要的最小时间轴规则：
1. 片段按开始时间排序。
2. 开始时间不能早于 0。
3. 相邻片段不能互相重叠。
"""

from __future__ import annotations

from importlib import import_module

import pytest

from core.dto.subtitle_dto import SubtitleSegmentDTO


def _load_aligner_class() -> type[object]:
    """延迟加载未来要实现的字幕时间轴规整类。"""

    try:
        module = import_module("infrastructure.subtitle.aligner")
    except ModuleNotFoundError:
        pytest.fail(
            "当前缺少字幕时间轴规整组件：请新增 "
            "`infrastructure.subtitle.aligner` 模块，并提供 "
            "`SubtitleAligner` 类。"
        )

    aligner_class = getattr(module, "SubtitleAligner", None)
    if aligner_class is None:
        pytest.fail(
            "`infrastructure.subtitle.aligner` 中应定义 "
            "`SubtitleAligner` 类。"
        )

    return aligner_class


def _segment(
    segment_id: str,
    start_ms: int,
    end_ms: int,
    text: str,
    language: str = "zh-CN",
) -> SubtitleSegmentDTO:
    """构造字幕片段，避免每个测试重复写完整 DTO 字段。"""

    return SubtitleSegmentDTO(
        segment_id=segment_id,
        start_ms=start_ms,
        end_ms=end_ms,
        text=text,
        language=language,
    )


def _ranges(segments: list[SubtitleSegmentDTO]) -> list[tuple[int, int]]:
    """把字幕片段转成起止时间列表，方便断言时间轴结果。"""

    return [(segment.start_ms, segment.end_ms) for segment in segments]


def test_subtitle_aligner_sorts_segments_and_removes_timeline_overlap() -> None:
    """时间轴规整后，字幕应按开始时间排列且相邻片段不再重叠。"""

    # arrange：ASR 合并多个音频块后，可能出现顺序错乱和边界重叠。
    # 这里用乱序输入保护“先排序、再规整重叠”的基础行为。
    aligner_class = _load_aligner_class()
    aligner = aligner_class()
    segments = [
        _segment("seg-2", 900, 1_800, "第二句"),
        _segment("seg-1", 0, 1_000, "第一句"),
        _segment("seg-3", 1_700, 2_500, "第三句"),
    ]

    # act
    result = aligner.normalize_timeline(segments)

    # assert：期望输出仍保留原片段身份和文本，
    # 只把重叠片段的开始时间推到上一条结束之后。
    assert [segment.segment_id for segment in result] == ["seg-1", "seg-2", "seg-3"]
    assert [segment.text for segment in result] == ["第一句", "第二句", "第三句"]
    assert _ranges(result) == [
        (0, 1_000),
        (1_000, 1_800),
        (1_800, 2_500),
    ]


def test_subtitle_aligner_clamps_negative_start_time_to_zero() -> None:
    """负数开始时间应被规整为 0，避免写出非法字幕时间。"""

    # arrange：某些识别引擎或切块回填可能产生轻微负偏移。
    # `SRT` 时间轴不能小于 0，所以这里先用测试固定修正规则。
    aligner_class = _load_aligner_class()
    aligner = aligner_class()
    segments = [
        _segment("seg-1", -80, 900, "开头字幕"),
        _segment("seg-2", 1_000, 1_800, "后续字幕"),
    ]

    # act
    result = aligner.normalize_timeline(segments)

    # assert
    assert _ranges(result) == [
        (0, 900),
        (1_000, 1_800),
    ]
