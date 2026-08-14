"""字幕翻译用例模块。"""

from __future__ import annotations

from dataclasses import dataclass
import re
from uuid import uuid4

from core.domain.entities import Task
from core.domain.enums import TaskCheckpoint
from core.dto.subtitle_dto import TranslateSubtitlesInput, TranslateSubtitlesResult
from core.ports.events import TaskEventPublisher
from core.ports.repository import ProjectRepository, SubtitleRepository, TaskRepository
from core.ports.subtitle import SubtitleWriter
from core.ports.translator import Translator


@dataclass(slots=True)
class TranslateSubtitles:
    """负责把原文字幕交给翻译端口，并保存译文字幕。"""

    project_repository: ProjectRepository
    task_repository: TaskRepository
    subtitle_repository: SubtitleRepository
    translator: Translator
    event_publisher: TaskEventPublisher | None = None
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
            # 第一步：先检查结构化译文和正式字幕文件是否都存在。
            # 两者同时存在才算完整缓存，避免只剩数据库记录或只剩文件时误判成功。
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
            reused_translation = bool(cached_segments) and (
                subtitle_path is None or subtitle_path.exists()
            )

            if reused_translation:
                translated_segments = cached_segments
            else:
                # 第二步：翻译器只接收字幕片段和语言信息，守住云端隐私边界。
                translated_segments = self.translator.translate_segments(
                    segments=source_segments,
                    source_language=request.source_language,
                    target_language=request.target_language,
                    context=request.context,
                )
                self.subtitle_repository.save_translated_segments(
                    project_id=project.project_id,
                    target_language=request.target_language,
                    segments=translated_segments,
                )

                # 第三步：把译文写入正式字幕目录，导出用例后续只需要接收路径。
                if self.subtitle_writer is not None and subtitle_path is not None:
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

    def _safe_language_name(self, language: str) -> str:
        """把语言代码转换成不会改变目录层级的文件名片段。"""

        safe_name = re.sub(r"[^0-9A-Za-z_-]+", "_", language).strip("_")
        return safe_name or "translated"
