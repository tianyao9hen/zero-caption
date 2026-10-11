"""已有项目重新导出用例测试。

测试保护“读取当前结构化译文 -> 重写正式字幕 -> 调用导出器”的顺序，
避免单句编辑后继续复用旧旁车字幕。
"""

from pathlib import Path

from core.domain.entities import Project
from core.domain.enums import ExportMode, ProjectStatus
from core.dto.subtitle_dto import SubtitleSegmentDTO
from core.dto.task_dto import (
    ExportRecordDTO,
    ExportVideoInput,
    ReexportProjectInput,
)
from core.usecases.export_video import ExportVideo
from core.usecases.reexport_project import ReexportProject
from infrastructure.storage.memory_repositories import (
    InMemoryExportRecordRepository,
    InMemoryProjectRepository,
    InMemorySubtitleRepository,
    InMemoryTaskRepository,
)
from infrastructure.subtitle.srt_writer import SrtWriter


class RecordingExporter:
    """记录导出请求，并写入一个最小成品文件。"""

    def __init__(self) -> None:
        self.requests = []

    def export(self, request):
        """保存请求并模拟本地导出产物。"""

        self.requests.append(request)
        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        request.output_path.write_bytes(b"exported video")
        return ExportRecordDTO(
            project_id=request.project_id,
            source_video=request.source_video,
            subtitle_path=request.subtitle_path,
            output_path=request.output_path,
            mode=request.mode,
        )


def test_reexport_project_uses_current_translation_and_updates_mode(tmp_path) -> None:
    """重新导出应采用当前译文，并持久化用户新选择的导出模式。"""

    # arrange：项目先保存两条已经人工校对过的译文。
    projects = InMemoryProjectRepository()
    tasks = InMemoryTaskRepository()
    subtitles = InMemorySubtitleRepository()
    exports = InMemoryExportRecordRepository()
    source_video = tmp_path / "lesson.mp4"
    source_video.write_bytes(b"source video")
    project = Project(
        project_id="project-reexport",
        source_video=source_video,
        source_language="en",
        target_language="zh-CN",
        workspace_dir=tmp_path / "project-reexport",
        output_path=tmp_path / "project-reexport" / "exports" / "lesson.mp4",
    )
    project.mark_completed()
    projects.save(project)
    source_segments = [
        SubtitleSegmentDTO("segment-1", 0, 1_000, "hello", "en"),
        SubtitleSegmentDTO("segment-2", 1_000, 2_000, "world", "en"),
    ]
    subtitles.save_source_segments(project.project_id, source_segments)
    subtitles.save_translated_segments(
        project.project_id,
        project.target_language,
        [
            SubtitleSegmentDTO("segment-1", 0, 1_000, "你好", "zh-CN"),
            SubtitleSegmentDTO(
                "segment-2",
                1_000,
                2_000,
                "人工校对后的世界",
                "zh-CN",
            ),
        ],
    )
    exporter = RecordingExporter()
    export_video = ExportVideo(
        project_repository=projects,
        task_repository=tasks,
        export_record_repository=exports,
        exporter=exporter,
    )
    usecase = ReexportProject(
        project_repository=projects,
        subtitle_repository=subtitles,
        subtitle_writer=SrtWriter(),
        export_video=export_video,
    )

    # act：切换为烧录字幕，并选择一个新的成品保存地址。
    selected_output = tmp_path / "chosen-results" / "lesson-final.mp4"
    result = usecase.execute(
        ReexportProjectInput(
            project_id=project.project_id,
            mode=ExportMode.BURN_IN,
            output_path=selected_output,
        )
    )

    # assert：本次请求缺少现成成品，因此导出器先在工作区烧录一份，
    # 再把这份成品交给用户选择的目录，后续下载就不必重新编码。
    assert len(exporter.requests) == 2
    first_request, second_request = exporter.requests
    assert first_request.task_type == "prepare_product"
    assert first_request.prepared_source_path is None
    assert first_request.output_path == (
        tmp_path / "project-reexport" / "exports" / "lesson-烧录成品.mp4"
    )
    assert second_request.task_type == "export_video"
    assert second_request.prepared_source_path == first_request.output_path
    assert second_request.output_path == selected_output
    subtitle_path = Path(first_request.subtitle_path)
    assert "人工校对后的世界" in subtitle_path.read_text(encoding="utf-8")
    assert result.export_record.mode is ExportMode.BURN_IN
    assert result.export_record.output_path == selected_output
    assert result.export_record.output_path.read_bytes() == b"exported video"
    stored_project = projects.get_by_id(project.project_id)
    assert stored_project.export_mode is ExportMode.BURN_IN
    assert stored_project.output_path == selected_output
    assert stored_project.prepared_output_path == first_request.output_path
    assert stored_project.status is ProjectStatus.COMPLETED


class ProgressReportingExporter:
    """模拟长耗时导出器：回调两次进度后写出成品。"""

    def __init__(self) -> None:
        self.reported: list[tuple[int, int]] = []

    def export(self, request):
        """回报两段进度后返回导出记录。"""

        if request.progress_callback is not None:
            request.progress_callback(30_000, 120_000)
            request.progress_callback(90_000, 120_000)
            self.reported.append((30_000, 120_000))
        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        request.output_path.write_bytes(b"exported video")
        return ExportRecordDTO(
            project_id=request.project_id,
            source_video=request.source_video,
            subtitle_path=request.subtitle_path,
            output_path=request.output_path,
            mode=request.mode,
        )


class CollectingPublisher:
    """收集用例发布的任务快照，用于检查进度消息是否被写入任务。"""

    def __init__(self) -> None:
        self.messages: list[str] = []
        self.snapshots: list[tuple[str, str]] = []

    def publish(self, task) -> None:
        """记录任务消息和步骤文案。"""

        self.messages.append(task.message)
        self.snapshots.append((task.status.value, task.current_step))


class FailingExporter:
    """模拟导出器在写盘阶段失败，用于验证失败收口文案。"""

    def export(self, request):
        """直接抛出磁盘写入异常。"""

        raise OSError("成品路径不可写")


def test_export_video_final_step_leaves_running_progress_behind(tmp_path) -> None:
    """烧录完成后，当前步骤不应继续停留在最后一条进行时进度。

    回归背景：导出成功时`message` 会正确变成“下载完成：xxx”，但
    `current_step` 曾保持为“正在生成成品 99%（…）”，界面因此永远显示
    任务卡在 99%，而文件其实已经落盘。
    """

    # arrange：一个已完成翻译的项目，导出器会先回报一次 99% 左右的进度。
    projects = InMemoryProjectRepository()
    tasks = InMemoryTaskRepository()
    export_records = InMemoryExportRecordRepository()
    project = Project(
        project_id="project-final-step",
        source_video=tmp_path / "source.mp4",
        source_language="en",
        target_language="zh-CN",
        workspace_dir=tmp_path / "project-final-step",
    )
    project.mark_completed()
    projects.save(project)
    exporter = ProgressReportingExporter()
    publisher = CollectingPublisher()
    usecase = ExportVideo(
        project_repository=projects,
        task_repository=tasks,
        export_record_repository=export_records,
        exporter=exporter,
        event_publisher=publisher,
    )

    # act：执行一次烧录导出。
    result = usecase.execute(
        ExportVideoInput(
            project_id=project.project_id,
            source_video=project.source_video,
            subtitle_path=tmp_path / "translated.srt",
            output_path=tmp_path / "exports" / "output.mp4",
            mode=ExportMode.BURN_IN,
        )
    )

    # assert：返回的任务与最后一条事件都应是完成态步骤，而不是进行时进度。
    assert result.task.status.value == "succeeded"
    assert result.task.current_step == "已生成成品"
    assert "正在生成成品" not in result.task.current_step
    assert publisher.snapshots[-1] == ("succeeded", "已生成成品")
    # 运行期确实出现过进行时进度，说明这条用例真的覆盖了“先 99% 再完成”。
    assert any("正在生成成品" in step for _status, step in publisher.snapshots[:-1])


def test_export_video_failure_step_reports_failure_not_progress(tmp_path) -> None:
    """烧录失败时，当前步骤应指向失败，而不是停在进行时进度上。"""

    # arrange：注入一个必然失败的导出器。
    projects = InMemoryProjectRepository()
    tasks = InMemoryTaskRepository()
    export_records = InMemoryExportRecordRepository()
    project = Project(
        project_id="project-fail-step",
        source_video=tmp_path / "source.mp4",
        source_language="en",
        target_language="zh-CN",
        workspace_dir=tmp_path / "project-fail-step",
    )
    project.mark_completed()
    projects.save(project)
    publisher = CollectingPublisher()
    usecase = ExportVideo(
        project_repository=projects,
        task_repository=tasks,
        export_record_repository=export_records,
        exporter=FailingExporter(),
        event_publisher=publisher,
    )

    # act / assert：导出异常应向上抛出，同时任务按失败收口。
    try:
        usecase.execute(
            ExportVideoInput(
                project_id=project.project_id,
                source_video=project.source_video,
                subtitle_path=tmp_path / "translated.srt",
                output_path=tmp_path / "exports" / "output.mp4",
                mode=ExportMode.BURN_IN,
            )
        )
    except OSError:
        pass
    else:  # pragma: no cover - 导出器必然抛错，走到这里说明用例吞掉了异常
        raise AssertionError("导出失败时应把异常继续抛给调用方。")

    stored_tasks = tasks.list_by_project(project.project_id)
    assert stored_tasks, "失败的导出任务也应持久化，便于界面显示失败原因。"
    failed_task = stored_tasks[-1]
    assert failed_task.status.value == "failed"
    assert failed_task.current_step == "成品生成失败"
    assert publisher.snapshots[-1] == ("failed", "成品生成失败")


def test_export_video_reports_burn_in_progress_to_task_and_events(tmp_path) -> None:
    """烧录进度应写入任务记录并发布事件，避免界面长时间没有任何反馈。"""

    # arrange：一个已完成翻译的项目，导出器会回报两段进度。
    projects = InMemoryProjectRepository()
    tasks = InMemoryTaskRepository()
    export_records = InMemoryExportRecordRepository()
    project = Project(
        project_id="project-progress",
        source_video=tmp_path / "source.mp4",
        source_language="en",
        target_language="zh-CN",
        workspace_dir=tmp_path / "project-progress",
    )
    project.mark_completed()
    projects.save(project)
    exporter = ProgressReportingExporter()
    publisher = CollectingPublisher()
    usecase = ExportVideo(
        project_repository=projects,
        task_repository=tasks,
        export_record_repository=export_records,
        exporter=exporter,
        event_publisher=publisher,
    )

    # act：执行一次烧录导出。
    usecase.execute(
        ExportVideoInput(
            project_id=project.project_id,
            source_video=project.source_video,
            subtitle_path=tmp_path / "translated.srt",
            output_path=tmp_path / "exports" / "output.mp4",
            mode=ExportMode.BURN_IN,
        )
    )

    # assert：导出器拿到进度回调，任务消息包含百分比和已处理时长。
    assert exporter.reported == [(30_000, 120_000)]
    assert any("正在生成成品 25%" in message for message in publisher.messages)
    assert any("00:00:30" in message and "00:02:00" in message for message in publisher.messages)
    # 第二次回调紧接第一次发生，会被最小上报间隔合并掉，避免烧录期间
    # 每秒写库数十次、拖慢重新编码本身。
    assert not any("正在生成成品 75%" in message for message in publisher.messages)

