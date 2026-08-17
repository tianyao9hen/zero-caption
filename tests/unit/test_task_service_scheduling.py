"""任务服务的分阶段资源调度测试。

测试只关心核心服务如何标记高资源步骤，不启动真实识别模型、网络翻译或
视频导出进程，从而把并发策略与具体适配器行为分开验证。
"""

from types import SimpleNamespace
from unittest.mock import Mock

from core.domain.entities import Task
from core.domain.enums import ExportMode
from core.dto.subtitle_dto import TranscribeVideoInput, TranslateSubtitlesInput
from core.dto.task_dto import ExportVideoInput, ReexportProjectInput
from core.services.task_service import TaskService


class RecordingResourceScheduler:
    """记录受限操作名称，并立即执行操作的测试调度器。"""

    def __init__(self) -> None:
        self.operation_names: list[str] = []

    def run(self, operation_name, operation):
        """记录调度请求，随后同步返回原操作结果。"""

        self.operation_names.append(operation_name)
        return operation()


def _completed_result(task_type: str):
    """构造带任务快照的最小用例结果，满足服务摘要更新要求。"""

    task = Task(f"task-{task_type}", "project-1", task_type)
    task.mark_succeeded("测试完成")
    return SimpleNamespace(task=task)


def test_task_service_limits_transcription_and_export_but_not_translation(
    tmp_path,
) -> None:
    """识别和导出应进入资源调度器，纯文本翻译不应被串行闸门限制。"""

    # arrange：每个用例返回独立任务快照，调度器只记录经过它的阶段。
    transcription = Mock()
    transcription.execute.return_value = _completed_result("transcribe_video")
    translation = Mock()
    translation.execute.return_value = _completed_result("translate_subtitles")
    export = Mock()
    export.execute.return_value = _completed_result("export_video")
    reexport = Mock()
    reexport.execute.return_value = _completed_result("export_video")
    scheduler = RecordingResourceScheduler()
    service = TaskService(
        transcribe_video_usecase=transcription,
        translate_subtitles_usecase=translation,
        export_video_usecase=export,
        reexport_project_usecase=reexport,
        resource_scheduler=scheduler,
    )

    # act：依次执行主链路中会被单独调用的三个阶段和重新导出入口。
    service.transcribe_video(TranscribeVideoInput(project_id="project-1"))
    service.translate_subtitles(
        TranslateSubtitlesInput(
            project_id="project-1",
            source_language="en",
            target_language="zh-CN",
        )
    )
    service.export_video(
        ExportVideoInput(
            project_id="project-1",
            source_video=tmp_path / "source.mp4",
            subtitle_path=tmp_path / "translated.srt",
            output_path=tmp_path / "output.mp4",
            mode=ExportMode.SOFT_SUBTITLE,
        )
    )
    service.reexport_project(
        ReexportProjectInput(
            project_id="project-1",
            mode=ExportMode.BURN_IN,
            output_path=tmp_path / "second-output.mp4",
        )
    )

    # assert：网络翻译未占用本机高资源槽位，两个导出入口共享同一类别。
    assert scheduler.operation_names == [
        "transcribe_video",
        "export_video",
        "export_video",
    ]
