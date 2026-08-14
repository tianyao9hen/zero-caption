"""`SRT` 文本写出组件单元测试。

这组测试只固定字幕片段到 `SRT` 文本的转换结果。
文件落盘可以在后续实现中补充，但本次 S2-11 先把纯文本格式钉住。
"""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
from uuid import uuid4

import pytest

from core.dto.subtitle_dto import SubtitleSegmentDTO


def _load_writer_class() -> type[object]:
    """延迟加载未来要实现的 `SRT` 写出类。"""

    try:
        module = import_module("infrastructure.subtitle.srt_writer")
    except ModuleNotFoundError:
        pytest.fail(
            "当前缺少 `SRT` 写出组件：请新增 "
            "`infrastructure.subtitle.srt_writer` 模块，并提供 "
            "`SrtWriter` 类。"
        )

    writer_class = getattr(module, "SrtWriter", None)
    if writer_class is None:
        pytest.fail(
            "`infrastructure.subtitle.srt_writer` 中应定义 "
            "`SrtWriter` 类。"
        )

    return writer_class


def _segment(
    segment_id: str,
    start_ms: int,
    end_ms: int,
    text: str,
    language: str = "zh-CN",
) -> SubtitleSegmentDTO:
    """构造字幕片段，保持测试输入清晰。"""

    return SubtitleSegmentDTO(
        segment_id=segment_id,
        start_ms=start_ms,
        end_ms=end_ms,
        text=text,
        language=language,
    )


def test_srt_writer_renders_numbered_blocks_with_srt_timestamp_format() -> None:
    """`SRT` 文本应包含序号、时间范围、字幕正文和空行分隔。"""

    # arrange：毫秒值故意包含小时、分钟、秒和毫秒，
    # 用来保护 `SRT` 要求的 `HH:MM:SS,mmm` 时间格式。
    writer_class = _load_writer_class()
    writer = writer_class()
    segments = [
        _segment("seg-1", 0, 1_234, "第一句字幕"),
        _segment("seg-2", 3_661_005, 3_662_250, "第二句字幕"),
    ]

    # act：这里约定 `to_text` 只返回字符串，不直接写文件。
    # 这样组件可以先被核心流程和文件写出流程共同复用。
    result = writer.to_text(segments)

    # assert：末尾保留一个换行，方便后续直接写入 `.srt` 文件。
    assert result == (
        "1\n"
        "00:00:00,000 --> 00:00:01,234\n"
        "第一句字幕\n"
        "\n"
        "2\n"
        "01:01:01,005 --> 01:01:02,250\n"
        "第二句字幕\n"
        "\n"
    )


def test_srt_writer_preserves_multiline_subtitle_text() -> None:
    """字幕正文包含换行时，`SRT` 输出应原样保留多行文本。"""

    # arrange：双语或人工修订字幕可能已经包含换行。
    # 写出组件不应把正文合并成一行，否则会破坏字幕排版。
    writer_class = _load_writer_class()
    writer = writer_class()
    segments = [
        _segment("seg-1", 500, 2_000, "第一行\n第二行"),
    ]

    # act
    result = writer.to_text(segments)

    # assert
    assert result == (
        "1\n"
        "00:00:00,500 --> 00:00:02,000\n"
        "第一行\n"
        "第二行\n"
        "\n"
    )


def test_srt_writer_writes_utf8_file_to_target_path() -> None:
    """`SRT` 写出组件应能把字幕文本稳定保存到指定文件。"""

    # arrange：正式字幕会落在项目级 `subtitles/` 目录。
    # 当前沙箱不能稳定使用系统临时目录，所以这里使用仓库内已忽略的 `.tmp` 目录。
    writer_class = _load_writer_class()
    writer = writer_class()
    output_path = (
        Path(".tmp")
        / "srt_writer"
        / str(uuid4())
        / "subtitles"
        / "source.srt"
    )
    segments = [
        _segment("seg-1", 0, 1_000, "落盘字幕"),
    ]

    # act：`write_file` 负责创建父目录并使用 UTF-8 写入。
    try:
        result_path = writer.write_file(segments, output_path)

        # assert：返回路径方便后续用例继续传递字幕产物位置。
        assert result_path == output_path
        assert output_path.read_text(encoding="utf-8") == (
            "1\n"
            "00:00:00,000 --> 00:00:01,000\n"
            "落盘字幕\n"
            "\n"
        )
    finally:
        # 测试结束后只清理本测试创建的唯一文件和空目录，
        # 避免把仓库里的其他测试产物一并删除。
        try:
            output_path.unlink(missing_ok=True)
        except OSError:
            pass
        for directory in [
            output_path.parent,
            output_path.parent.parent,
            output_path.parent.parent.parent,
        ]:
            if directory.exists():
                try:
                    directory.rmdir()
                except OSError:
                    pass
