"""视频导出用例模块。"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from core.domain.entities import Task
from core.domain.enums import TaskCheckpoint
from core.dto.task_dto import ExportVideoInput, ExportVideoResult
from core.ports.events import TaskEventPublisher
from core.ports.exporter import VideoExporter
from core.ports.repository import ExportRecordRepository, ProjectRepository, TaskRepository


@dataclass(slots=True)
class ExportVideo:
    """负责调用导出端口并保存导出记录。"""

    project_repository: ProjectRepository
    task_repository: TaskRepository
    export_record_repository: ExportRecordRepository
    exporter: VideoExporter
    event_publisher: TaskEventPublisher | None = None

    def execute(self, request: ExportVideoInput) -> ExportVideoResult:
        """执行导出流程。"""

        project = self.project_repository.get_by_id(request.project_id)
        if project is None:
            raise ValueError(f"未找到项目：{request.project_id}")

        project.mark_processing()
        self.project_repository.save(project)

        task = Task(
            task_id=f"task-{uuid4().hex}",
            project_id=project.project_id,
            task_type="export_video",
        )
        task.start("开始导出")
        task.update_progress(
            progress=60,
            current_step="调用导出器",
            checkpoint=TaskCheckpoint.TRANSLATED,
            message="字幕已准备好",
        )
        self.task_repository.save(task)
        if self.event_publisher is not None:
            self.event_publisher.publish(task)

        export_record = self.exporter.export(request)
        self.export_record_repository.save(export_record)
        task.mark_succeeded("导出完成", checkpoint=TaskCheckpoint.EXPORTED)
        self.task_repository.save(task)
        if self.event_publisher is not None:
            self.event_publisher.publish(task)

        project.mark_completed()
        self.project_repository.save(project)

        return ExportVideoResult(
            project=project,
            task=task,
            export_record=export_record,
        )
