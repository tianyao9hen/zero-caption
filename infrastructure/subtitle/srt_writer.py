"""`SRT` 字幕写出组件。

这个模块位于基础设施层，负责把项目内部的 `SubtitleSegmentDTO`
转换成标准 `SRT` 文本，并在需要时写入本地文件系统。
它不做翻译、不做样式渲染，也不调用视频导出逻辑。
"""

from __future__ import annotations

from pathlib import Path

from core.dto.subtitle_dto import SubtitleSegmentDTO


class SrtWriter:
    """把字幕片段渲染并写出为 `SRT` 格式。

    `SRT` 是阶段 2 原文字幕的最小交付格式。这个类的公开方法分成两层：
    `to_text` 只生成字符串，便于测试和后续复用；
    `write_file` 负责真正落盘，便于用例把字幕保存到项目目录。
    """

    def to_text(self, segments: list[SubtitleSegmentDTO]) -> str:
        """把字幕片段列表转换成 `SRT` 文本。

        参数：
            segments：已经完成去重和时间轴规整的字幕片段。

        返回：
            符合 `SRT` 基础格式的字符串，末尾保留换行，
            方便直接写入 `.srt` 文件。
        """

        blocks: list[str] = []

        # `SRT` 的序号从 1 开始。这里不使用片段自己的 `segment_id`，
        # 是因为写出文件时需要连续数字，播放器通常也按这个序号解析。
        for index, segment in enumerate(segments, start=1):
            blocks.extend(
                [
                    str(index),
                    (
                        f"{self._format_timestamp(segment.start_ms)} --> "
                        f"{self._format_timestamp(segment.end_ms)}"
                    ),
                    segment.text,
                    "",
                ]
            )

        if not blocks:
            return ""

        return "\n".join(blocks) + "\n"

    def write_file(
        self,
        segments: list[SubtitleSegmentDTO],
        output_path: str | Path,
    ) -> Path:
        """把字幕片段以 UTF-8 编码写入指定 `.srt` 文件。

        参数：
            segments：要写出的字幕片段列表。
            output_path：目标文件路径，可以是字符串或 `Path`。

        返回：
            写入后的目标路径，便于后续用例继续传递字幕产物。

        副作用：
            会创建目标文件的父目录，并覆盖同名文件。
        """

        target_path = Path(output_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(self.to_text(segments), encoding="utf-8")
        return target_path

    def _format_timestamp(self, milliseconds: int) -> str:
        """把毫秒数格式化成 `SRT` 要求的 `HH:MM:SS,mmm`。"""

        safe_milliseconds = max(0, milliseconds)
        hours, remainder = divmod(safe_milliseconds, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        seconds, millis = divmod(remainder, 1_000)
        return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"
