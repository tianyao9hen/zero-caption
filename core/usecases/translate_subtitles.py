"""字幕翻译用例模块。"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from core.domain.entities import Task
from core.domain.enums import TaskCheckpoint
from core.dto.subtitle_dto import TranslateSubtitlesInput, TranslateSubtitlesResult
from core.ports.events import TaskEventPublisher
from core.ports.repository import ProjectRepository, SubtitleRepository, TaskRepository
from core.ports.translator import Translator


@dataclass(slots=True)
class TranslateSubtitles:
    """负责把原文字幕交给翻译端口，并保存译文字幕。"""

    project_repository: ProjectRepository
    task_repository: TaskRepository
    subtitle_repository: SubtitleRepository
    translator: Translator
    event_publisher: TaskEventPublisher | None = None

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
        task.mark_succeeded("翻译完成", checkpoint=TaskCheckpoint.TRANSLATED)
        self.task_repository.save(task)
        if self.event_publisher is not None:
            self.event_publisher.publish(task)

        return TranslateSubtitlesResult(
            project_id=project.project_id,
            task=task,
            translated_segments=translated_segments,
        )
