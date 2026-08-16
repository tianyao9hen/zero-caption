"""字幕逐句翻译用例模块。

核心层在这里明确保证“一条字幕对应一次模型调用”，并在每条完成后保存
检查点和发布展示事件。翻译器如何访问网络仍由基础设施适配器负责。
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from uuid import uuid4

from core.domain.entities import Task
from core.domain.enums import TaskCheckpoint
from core.dto.subtitle_dto import (
    SubtitleSegmentDTO,
    TranslateSubtitlesInput,
    TranslateSubtitlesResult,
    TranslationProgressDTO,
)
from core.ports.events import TaskEventPublisher, TranslationProgressPublisher
from core.ports.repository import ProjectRepository, SubtitleRepository, TaskRepository
from core.ports.subtitle import SubtitleWriter
from core.ports.translator import Translator


@dataclass(slots=True)
class TranslateSubtitles:
    """逐条翻译原文字幕，并在每条完成后保存和发布结果。"""

    project_repository: ProjectRepository
    task_repository: TaskRepository
    subtitle_repository: SubtitleRepository
    translator: Translator
    event_publisher: TaskEventPublisher | None = None
    translation_event_publisher: TranslationProgressPublisher | None = None
    subtitle_writer: SubtitleWriter | None = None

    def execute(self, request: TranslateSubtitlesInput) -> TranslateSubtitlesResult:
        """执行翻译流程。"""

        project = self.project_repository.get_by_id(request.project_id)
        if project is None:
            raise ValueError(f"未找到项目：{request.project_id}")

        source_segments = self.subtitle_repository.get_source_segments(project.project_id)
        if not source_segments:
            raise ValueError("翻译前必须先有原文字幕。")

        project.mark_processing()
        self.project_repository.save(project)

        task = Task(
            task_id=f"task-{uuid4().hex}",
            project_id=project.project_id,
            task_type="translate_subtitles",
        )
        task.start("开始翻译")
        task.update_progress(
            progress=40,
            current_step="调用翻译引擎",
            checkpoint=TaskCheckpoint.TRANSCRIBED,
            message="原文字幕已准备好",
        )
        self.task_repository.save(task)
        if self.event_publisher is not None:
            self.event_publisher.publish(task)

        try:
            # 第一步：先读取已经持久化的结构化译文。
            # 数据完整时可直接重建缺失的字幕文件，不需要再次访问大模型。
            subtitle_path = None
            if self.subtitle_writer is not None:
                language_name = self._safe_language_name(request.target_language)
                subtitle_path = project.workspace_dir / "subtitles" / (
                    f"translated-{language_name}.srt"
                )
            cached_segments = self.subtitle_repository.get_translated_segments(
                project.project_id,
                request.target_language,
            )
            cached_by_id = {
                segment.segment_id: segment for segment in cached_segments
            }
            reused_translation = len(cached_segments) == len(source_segments) and all(
                segment.segment_id in cached_by_id for segment in source_segments
            )

            # 第二步：按原始顺序逐条处理。即使翻译端口保留列表参数，
            # 核心用例每次也只传入一个片段，从业务层保证一次字幕对应一次请求。
            translated_segments: list[SubtitleSegmentDTO] = []
            total_segments = len(source_segments)
            for current_index, source_segment in enumerate(source_segments, start=1):
                translated_segment = cached_by_id.get(source_segment.segment_id)
                restored_from_cache = translated_segment is not None
                if translated_segment is None:
                    translated_segment = self._translate_one(
                        source_segment=source_segment,
                        source_language=request.source_language,
                        target_language=request.target_language,
                        context=request.context,
                    )

                translated_segments.append(translated_segment)

                # 第三步：每完成一条就保存当前有序结果。
                # 如果后续网络请求失败，用户下次重试时可以继续复用已经完成的字幕。
                self.subtitle_repository.save_translated_segments(
                    project_id=project.project_id,
                    target_language=request.target_language,
                    segments=translated_segments,
                )

                progress = 40 + round(current_index / total_segments * 55)
                task.update_progress(
                    progress=progress,
                    current_step=f"逐句翻译 {current_index}/{total_segments}",
                    checkpoint=TaskCheckpoint.TRANSCRIBED,
                    message=(
                        f"已恢复第 {current_index} 条译文"
                        if restored_from_cache
                        else f"已翻译第 {current_index} 条字幕"
                    ),
                )
                self.task_repository.save(task)
                if self.event_publisher is not None:
                    self.event_publisher.publish(task)
                if self.translation_event_publisher is not None:
                    self.translation_event_publisher.publish_translation(
                        TranslationProgressDTO(
                            task_id=task.task_id,
                            current_index=current_index,
                            total_segments=total_segments,
                            source_text=source_segment.text,
                            translated_text=translated_segment.text,
                            project_id=project.project_id,
                            segment_id=source_segment.segment_id,
                            start_ms=source_segment.start_ms,
                            end_ms=source_segment.end_ms,
                        )
                    )

            # 第四步：完整译文准备好后再生成正式字幕文件。
            # 缓存完整且文件仍在时直接复用；缺失文件时只重写本地文件，不重复访问模型。
            if (
                self.subtitle_writer is not None
                and subtitle_path is not None
                and (not reused_translation or not subtitle_path.exists())
            ):
                subtitle_path = self.subtitle_writer.write_file(
                    translated_segments,
                    subtitle_path,
                )

            task.mark_succeeded(
                "已复用译文字幕" if reused_translation else "翻译完成",
                checkpoint=TaskCheckpoint.TRANSLATED,
            )
            self.task_repository.save(task)
            if self.event_publisher is not None:
                self.event_publisher.publish(task)

            return TranslateSubtitlesResult(
                project_id=project.project_id,
                task=task,
                translated_segments=translated_segments,
                subtitle_path=subtitle_path,
                reused_translation=reused_translation,
            )
        except Exception as exc:
            error_message = str(exc) or exc.__class__.__name__
            task.mark_failed(error_message)
            project.mark_failed(error_message)
            self.task_repository.save(task)
            self.project_repository.save(project)
            if self.event_publisher is not None:
                self.event_publisher.publish(task)
            raise

    def _translate_one(
        self,
        source_segment: SubtitleSegmentDTO,
        source_language: str,
        target_language: str,
        context: str | None,
    ) -> SubtitleSegmentDTO:
        """调用一次翻译端口，并把结果规整回原字幕时间轴。"""

        result = self.translator.translate_segments(
            segments=[source_segment],
            source_language=source_language,
            target_language=target_language,
            context=context,
        )
        if len(result) != 1 or not result[0].text.strip():
            raise ValueError("逐句翻译必须返回且只返回一条非空字幕。")

        # 时间轴和编号始终以本地原字幕为准，模型只负责生成文本。
        # 这样外部服务即使返回了错误编号，也不会破坏字幕顺序和对齐关系。
        return SubtitleSegmentDTO(
            segment_id=source_segment.segment_id,
            start_ms=source_segment.start_ms,
            end_ms=source_segment.end_ms,
            text=result[0].text.strip(),
            language=target_language,
        )

    def _safe_language_name(self, language: str) -> str:
        """把语言代码转换成不会改变目录层级的文件名片段。"""

        safe_name = re.sub(r"[^0-9A-Za-z_-]+", "_", language).strip("_")
        return safe_name or "translated"
