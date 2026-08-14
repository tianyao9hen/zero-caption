"""ASS 写出测试，保护时间格式、默认样式和文本转义。"""

from core.dto.subtitle_dto import SubtitleSegmentDTO
from infrastructure.subtitle.ass_writer import AssWriter


def test_ass_writer_emits_style_events_and_escaped_text() -> None:
    """ASS 文本应包含可渲染样式、事件和安全的字幕正文。"""

    text = AssWriter().to_text([
        SubtitleSegmentDTO("s1", 0, 1_230, "第一行\n{重点}", "zh-CN")
    ])

    assert "[V4+ Styles]" in text
    assert "[Events]" in text
    assert "Dialogue: 0,0:00:00.00,0:00:01.23" in text
    assert r"第一行\N\{重点\}" in text
