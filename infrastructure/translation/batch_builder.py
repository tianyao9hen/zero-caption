"""字幕翻译批次构造器。

批次构造只处理字幕文本如何分组，不负责发送网络请求。
这样可以单独测试字符数限制和顺序保持，也能避免翻译适配器接触项目媒体路径。
"""

from __future__ import annotations

from dataclasses import dataclass

from core.dto.subtitle_dto import SubtitleSegmentDTO


@dataclass(frozen=True, slots=True)
class TranslationBatch:
    """表示一次远程翻译请求所需的最小字幕文本集合。"""

    segments: tuple[SubtitleSegmentDTO, ...]
    source_language: str
    target_language: str
    context: str | None = None

    @property
    def segment_ids(self) -> tuple[str, ...]:
        """返回当前批次的字幕编号，便于响应回填。"""

        return tuple(segment.segment_id for segment in self.segments)


class TranslationBatchBuilder:
    """按字幕条数和正文字符数构造有序翻译批次。"""

    def __init__(
        self,
        max_segments: int = 20,
        max_characters: int = 4_000,
    ) -> None:
        """设置单次请求的上限。

        参数：
            max_segments：一个批次最多包含的字幕条数。
            max_characters：一个批次最多包含的正文字符数。
        """

        if max_segments <= 0:
            raise ValueError("翻译批次的字幕条数上限必须大于 0。")
        if max_characters <= 0:
            raise ValueError("翻译批次的字符数上限必须大于 0。")
        self.max_segments = max_segments
        self.max_characters = max_characters

    def build_batches(
        self,
        segments: list[SubtitleSegmentDTO],
        source_language: str,
        target_language: str,
        context: str | None = None,
    ) -> list[TranslationBatch]:
        """把字幕按输入顺序切成多个翻译批次。

        单条字幕即使超过字符数上限，也会独立保留在自己的批次中，
        避免因为限制过严而静默丢失字幕内容。
        """

        batches: list[TranslationBatch] = []
        current: list[SubtitleSegmentDTO] = []
        current_characters = 0

        # 逐条累加而不是先把所有文本拼成一个大字符串，
        # 这样长视频字幕不会因为批次构造额外占用大量内存。
        for segment in segments:
            segment_characters = len(segment.text)
            exceeds_count = len(current) >= self.max_segments
            exceeds_characters = (
                current and current_characters + segment_characters > self.max_characters
            )
            if current and (exceeds_count or exceeds_characters):
                batches.append(
                    TranslationBatch(
                        segments=tuple(current),
                        source_language=source_language,
                        target_language=target_language,
                        context=context,
                    )
                )
                current = []
                current_characters = 0

            current.append(segment)
            current_characters += segment_characters

        if current:
            batches.append(
                TranslationBatch(
                    segments=tuple(current),
                    source_language=source_language,
                    target_language=target_language,
                    context=context,
                )
            )
        return batches
