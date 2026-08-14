"""字幕整理组件单元测试。

这组测试属于阶段 2 的字幕后处理测试，只固定“基础去重”的期望行为。
当前任务 S2-11 只新增测试，不实现 `infrastructure.subtitle` 组件；
因此测试会在真正组件缺失时给出清楚的失败信息，供 S2-12 按约定实现。
"""

from __future__ import annotations

from importlib import import_module

import pytest

from core.dto.subtitle_dto import SubtitleSegmentDTO


def _load_formatter_class() -> type[object]:
    """延迟加载未来要实现的字幕整理类。

    这里把导入动作放在测试函数运行阶段，而不是模块加载阶段，
    是为了让失败信息准确指向“缺少字幕整理组件”，
    避免 `pytest` 在收集测试时直接中断。
    """

    try:
        module = import_module("infrastructure.subtitle.formatter")
    except ModuleNotFoundError:
        pytest.fail(
            "当前缺少字幕整理组件：请新增 "
            "`infrastructure.subtitle.formatter` 模块，并提供 "
            "`SubtitleFormatter` 类。"
        )

    formatter_class = getattr(module, "SubtitleFormatter", None)
    if formatter_class is None:
        pytest.fail(
            "`infrastructure.subtitle.formatter` 中应定义 "
            "`SubtitleFormatter` 类。"
        )

    return formatter_class


def _segment(
    segment_id: str,
    start_ms: int,
    end_ms: int,
    text: str,
    language: str = "zh-CN",
) -> SubtitleSegmentDTO:
    """构造字幕片段，让测试数据聚焦在时间轴和文本差异上。"""

    return SubtitleSegmentDTO(
        segment_id=segment_id,
        start_ms=start_ms,
        end_ms=end_ms,
        text=text,
        language=language,
    )


def test_subtitle_formatter_removes_adjacent_duplicate_segments() -> None:
    """相邻片段文本相同且时间重叠时，应只保留第一条字幕。"""

    # arrange：ASR 在切块边界处可能重复输出同一句话。
    # 这里故意让前两条文本相同、时间有重叠，用来保护最基础的去重规则。
    formatter_class = _load_formatter_class()
    formatter = formatter_class()
    segments = [
        _segment("seg-1", 0, 1_500, "欢迎使用 zero-caption"),
        _segment("seg-2", 1_200, 2_600, "欢迎使用 zero-caption"),
        _segment("seg-3", 2_700, 4_000, "我们开始生成字幕"),
    ]

    # act：去重只负责删掉明显重复的片段，
    # 不在这里调整时间轴，也不负责写出 `SRT`。
    result = formatter.remove_duplicates(segments)

    # assert：保留结果应仍然是 `SubtitleSegmentDTO`，并保持原有顺序。
    assert result == [
        _segment("seg-1", 0, 1_500, "欢迎使用 zero-caption"),
        _segment("seg-3", 2_700, 4_000, "我们开始生成字幕"),
    ]


def test_subtitle_formatter_keeps_same_text_when_segments_are_not_adjacent() -> None:
    """同一句话隔着其他内容再次出现时，不应被当作重复字幕删除。"""

    # arrange：节目中可能在开头和结尾重复说同一句话。
    # 去重规则只处理相邻重复，避免误删真实内容。
    formatter_class = _load_formatter_class()
    formatter = formatter_class()
    segments = [
        _segment("seg-1", 0, 1_000, "谢谢观看"),
        _segment("seg-2", 1_200, 2_000, "下一段内容"),
        _segment("seg-3", 2_500, 3_500, "谢谢观看"),
    ]

    # act
    result = formatter.remove_duplicates(segments)

    # assert
    assert result == segments
