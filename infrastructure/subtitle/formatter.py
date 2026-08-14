"""字幕片段整理组件。

这个模块位于 `infrastructure/subtitle`，职责是做 ASR 结果的轻量清理。
阶段 2 只实现基础去重，不做复杂断句、翻译字幕合并或人工编辑逻辑。
"""

from __future__ import annotations

from core.dto.subtitle_dto import SubtitleSegmentDTO


class SubtitleFormatter:
    """清理原始字幕片段中的明显重复内容。

    ASR 在音频切块边界附近可能把同一句话识别两次。
    这个类只处理这种最保守的重复：相邻片段文本相同，并且时间范围重叠。
    它不会重新切句，也不会修改时间轴，避免和 `SubtitleAligner` 的职责混淆。
    """

    def remove_duplicates(
        self,
        segments: list[SubtitleSegmentDTO],
    ) -> list[SubtitleSegmentDTO]:
        """删除相邻且重叠的重复字幕片段。

        参数：
            segments：ASR 或上游流程产出的字幕片段列表。

        返回：
            新的字幕片段列表。返回值会保留原片段对象和原始顺序，
            只移除最明显的边界重复项。
        """

        deduplicated: list[SubtitleSegmentDTO] = []

        # 第一步：按输入顺序逐条检查，避免误删非相邻的重复台词。
        # 第二步：只有文本相同并且时间范围重叠时，才把当前片段视为重复。
        for segment in segments:
            if deduplicated and self._is_adjacent_duplicate(
                previous=deduplicated[-1],
                current=segment,
            ):
                continue

            deduplicated.append(segment)

        return deduplicated

    def _is_adjacent_duplicate(
        self,
        previous: SubtitleSegmentDTO,
        current: SubtitleSegmentDTO,
    ) -> bool:
        """判断当前片段是否是上一条字幕的边界重复。"""

        return (
            self._normalize_text(previous.text) == self._normalize_text(current.text)
            and current.start_ms < previous.end_ms
            and previous.start_ms < current.end_ms
        )

    def _normalize_text(self, text: str) -> str:
        """把文本规整成适合比较的形式。

        `split` 会按任意空白符切分文本，再用一个空格连接。
        这样可以忽略 ASR 偶尔多出的首尾空格或重复空格，
        但不会改变传出片段本身的字幕正文。
        """

        return " ".join(text.strip().split())
