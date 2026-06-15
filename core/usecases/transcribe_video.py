"""识别视频用例模块。"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from core.domain.entities import Task
from core.domain.enums import TaskCheckpoint
from core.dto.subtitle_dto import TranscribeVideoInput, TranscribeVideoResult
from core.ports.asr import AsrEngine
from core.ports.events import TaskEventPublisher
from core.ports.repository import ProjectRepository, SubtitleRepository, TaskRepository


@dataclass(slots=True)
class TranscribeVideo:
    """负责把音频交给 ASR 引擎，并产出原文字幕。"""

    project_repository: ProjectRepository
    task_repository: TaskRepository
    subtitle_repository: SubtitleRepository
    asr_engine: AsrEngine
    event_publisher: TaskEventPublisher | None = None

    def execute(self, request: TranscribeVideoInput) -> TranscribeVideoResult:
        """执行识别流程。"""

        project = self.project_repository.get_by_id(request.project_id)
        if project is None:
            raise ValueError(f"未找到项目：{request.project_id}")

        project.mark_processing()
        self.project_repository.save(project)

        task = Task(
            task_id=f"task-{uuid4().hex}",
            project_id=project.project_id,
            task_type="transcribe_video",
        )
        task.start("开始识别")
        task.update_progress(
            progress=30,
            current_step="调用识别引擎",
            checkpoint=TaskCheckpoint.AUDIO_EXTRACTED,
            message="音频已准备好",
        )
        self.task_repository.save(task)
        if self.event_publisher is not None:
            self.event_publisher.publish(task)

        segments = self.asr_engine.transcribe(
            audio_path=request.audio_path,
            language=request.language,
        )
        self.subtitle_repository.save_source_segments(project.project_id, segments)
        task.mark_succeeded("识别完成", checkpoint=TaskCheckpoint.TRANSCRIBED)
        self.task_repository.save(task)
        if self.event_publisher is not None:
            self.event_publisher.publish(task)

        return TranscribeVideoResult(
            project_id=project.project_id,
            task=task,
            source_segments=segments,
        )
