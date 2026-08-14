"""ASS 字幕写出适配器。"""

from __future__ import annotations

from pathlib import Path

from core.dto.subtitle_dto import SubtitleSegmentDTO


class AssWriter:
    """把字幕片段写成带默认样式的 `ASS` 文件。"""

    def to_text(self, segments: list[SubtitleSegmentDTO]) -> str:
        """生成可被 FFmpeg `subtitles` 滤镜读取的 ASS 文本。"""

        lines = [
            "[Script Info]",
            "ScriptType: v4.00+",
            "PlayResX: 1920",
            "PlayResY: 1080",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            "Style: Default,Microsoft YaHei,48,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,1,2,40,40,36,1",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]
        lines.extend(
            f"Dialogue: 0,{self._timestamp(segment.start_ms)},{self._timestamp(segment.end_ms)},Default,,0,0,0,,{self._escape(segment.text)}"
            for segment in segments
        )
        return "\n".join(lines) + "\n"

    def write_file(self, segments: list[SubtitleSegmentDTO], output_path: str | Path) -> Path:
        """以 UTF-8 编码写出 ASS 文件并返回目标路径。"""

        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.to_text(segments), encoding="utf-8")
        return target

    @staticmethod
    def _timestamp(milliseconds: int) -> str:
        """把毫秒转换成 ASS 所需的 `H:MM:SS.cc` 时间格式。"""

        safe = max(0, milliseconds)
        hours, remainder = divmod(safe, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        seconds, centiseconds = divmod(remainder, 1_000)
        return f"{hours}:{minutes:02}:{seconds:02}.{centiseconds // 10:02}"

    @staticmethod
    def _escape(text: str) -> str:
        """转义 ASS 控制字符，避免字幕文本改变渲染指令。"""

        return text.replace("\\", r"\\").replace("\n", r"\N").replace("{", r"\{").replace("}", r"\}")
