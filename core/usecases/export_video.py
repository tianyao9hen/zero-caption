"""视频导出用例模块。"""

from __future__ import annotations

from dataclasses import dataclass, replace
import os
import time
from uuid import uuid4

from core.domain.entities import Task
from core.domain.enums import TaskCheckpoint
from core.dto.task_dto import ExportVideoInput, ExportVideoResult
from core.ports.events import TaskEventPublisher
from core.ports.exporter import VideoExporter
from core.ports.repository import ExportRecordRepository, ProjectRepository, TaskRepository

# 烧录整段视频可能持续数十分钟。为了避免每次进度回调都写库并通知界面，
# 这里限制最小上报间隔；同时百分比只有跳变至少 1% 时才更新任务记录。
_PROGRESS_REPORT_INTERVAL_SECONDS = 1.0

# 同一个导出流程会被两种业务动作复用：用户点击“下载成品”，以及任务创建
# 流程在项目目录内预生成成品。两者的执行顺序完全一致，只有界面阶段名称和
# 完成文案不同，因此文案集中在这里按任务类型配置，避免散落到条件判断里。
_TASK_TYPE_LABELS: dict[str, dict[str, str]] = {
    "export_video": {
        "start": "开始导出",
        "ready": "字幕已准备好",
        "succeeded": "已生成成品",
        "failed": "成品生成失败",
        "success_prefix": "下载完成",
    },
    "prepare_product": {
        "start": "开始生成成品",
        "ready": "字幕已写入项目目录",
        "succeeded": "成品已就绪",
        "failed": "成品生成失败",
        "success_prefix": "成品已生成",
    },
}


def _labels_for(task_type: str) -> dict[str, str]:
    """按任务类型返回界面文案，未知类型回退到普通下载文案。"""

    return _TASK_TYPE_LABELS.get(task_type, _TASK_TYPE_LABELS["export_video"])


def _format_duration(milliseconds: int) -> str:
    """把毫秒格式化成 `时:分:秒`，供任务消息直接展示。"""

    safe_value = max(0, milliseconds)
    total_seconds = safe_value // 1_000
    hours, remainder = divmod(total_seconds, 3_600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}"


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

        # 输出覆盖源视频会让外挂复制触发同文件错误，也可能让 FFmpeg 在读取
        # 输入时截断原文件。这个约束属于核心业务安全边界，不能只依赖 UI。
        source_path = os.path.normcase(os.path.abspath(request.source_video))
        output_path = os.path.normcase(os.path.abspath(request.output_path))
        if source_path == output_path:
            raise ValueError("成品保存路径不能覆盖源视频，请选择其他文件名。")

        project = self.project_repository.get_by_id(request.project_id)
        if project is None:
            raise ValueError(f"未找到项目：{request.project_id}")

        project.mark_processing()
        self.project_repository.save(project)

        task = Task(
            task_id=f"task-{uuid4().hex}",
            project_id=project.project_id,
            task_type=request.task_type,
        )
        labels = _labels_for(request.task_type)
        task.start(labels["start"])
        task.update_progress(
            # 下载动作不属于视频处理总进度。任务仍记录为运行中，方便界面
            # 展示“正在生成”，但百分比保持 100%，不能让已完成任务倒退。
            # 预生成成品同样如此：它跑在翻译任务之后，属于最后一道附加步骤，
            # 不能让已经到 100% 的主链路进度倒退到识别或翻译阶段。
            progress=100,
            current_step=labels["start"],
            checkpoint=TaskCheckpoint.TRANSLATED,
            message=labels["ready"],
        )
        self.task_repository.save(task)
        if self.event_publisher is not None:
            self.event_publisher.publish(task)

        # 烧录会把整段视频重新编码。这里给导出器装上进度上报入口，
        # 让界面看到真实的已处理时长，而不是一直停在“字幕已准备好”。
        request = replace(
            request,
            progress_callback=self._build_progress_callback(task),
        )

        try:
            # 导出器只接收已经准备好的视频和字幕路径，
            # 具体是复制旁车文件还是重新编码由基础设施适配器决定。
            export_record = self.exporter.export(request)
            self.export_record_repository.save(export_record)
            # 不同导出模式的主要成品类型不同：烧录模式返回视频，外挂模式
            # 返回字幕文件。项目记录应保存适配器实际落盘的路径，供历史页
            # 和下一次下载正确复用，而不是盲目保存请求里的视频路径。
            project.output_path = export_record.output_path
            # 成功消息同时写入“下载完成”和实际落盘路径，避免后台最后一条
            # 100% 进度事件覆盖界面刚展示的下载结果，也便于历史任务核对文件。
            task.mark_succeeded(
                f"{labels['success_prefix']}：{export_record.output_path}",
                checkpoint=TaskCheckpoint.EXPORTED,
                # 运行期 `current_step` 最后一条是“正在生成成品 99%…”。
                # 这里必须显式换成完成态文案，否则任务成功后界面仍会显示
                # 那条进行时进度，让用户以为烧录卡在最后一步。
                current_step=labels["succeeded"],
            )
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
        except Exception as exc:
            error_message = str(exc) or exc.__class__.__name__
            # 失败时同样收口步骤文案。否则界面会停在“正在生成成品 99%”，
            # 看起来像还在正常运行，用户根本看不到真实失败原因。
            task.mark_failed(error_message, current_step=labels["failed"])
            project.mark_failed(error_message)
            self.task_repository.save(task)
            self.project_repository.save(project)
            if self.event_publisher is not None:
                self.event_publisher.publish(task)
            raise

    def _build_progress_callback(self, task: Task):
        """生成导出器使用的节流进度回调。

        回调由后台线程调用，因此只做“更新任务快照并发布事件”这两件
        线程安全的小事，不直接触碰任何界面对象。
        """

        state = {"last_reported_at": 0.0}

        def report(processed_ms: int, total_ms: int) -> None:
            """把已处理进度写入任务记录，并按最小间隔发布事件。"""

            now = time.monotonic()
            if now - state["last_reported_at"] < _PROGRESS_REPORT_INTERVAL_SECONDS:
                return
            state["last_reported_at"] = now

            if total_ms > 0:
                percent = min(99, max(0, round(processed_ms / total_ms * 100)))
                message = (
                    f"正在生成成品 {percent}%（{_format_duration(processed_ms)}"
                    f" / {_format_duration(total_ms)}）"
                )
            else:
                # 拿不到总时长时只展示已经处理的时间，避免显示错误百分比。
                message = f"正在生成成品，已处理 {_format_duration(processed_ms)}"

            # 导出百分比和视频处理总进度共用同一个字段。这里保持 100 以上
            # 的语义不变：总进度仍然展示下载阶段，消息里给出烧录细节。
            task.update_progress(
                progress=100,
                current_step=message,
                checkpoint=TaskCheckpoint.TRANSLATED,
                message=message,
            )
            self.task_repository.save(task)
            if self.event_publisher is not None:
                self.event_publisher.publish(task)

        return report
