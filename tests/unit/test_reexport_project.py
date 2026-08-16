"""已有项目重新导出用例测试。

测试保护“读取当前结构化译文 -> 重写正式字幕 -> 调用导出器”的顺序，
避免单句编辑后继续复用旧旁车字幕。
"""

from pathlib import Path

from core.domain.entities import Project
from core.domain.enums import ExportMode, ProjectStatus
from core.dto.subtitle_dto import SubtitleSegmentDTO
from core.dto.task_dto import ExportRecordDTO, ReexportProjectInput
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

    # act：把导出模式从默认外挂字幕切换为烧录字幕。
    result = usecase.execute(
        ReexportProjectInput(
            project_id=project.project_id,
            mode=ExportMode.BURN_IN,
        )
    )

    # assert：导出器收到的是刚重写的正式字幕，项目参数和状态也已更新。
    assert len(exporter.requests) == 1
    subtitle_path = Path(exporter.requests[0].subtitle_path)
    assert "人工校对后的世界" in subtitle_path.read_text(encoding="utf-8")
    assert result.export_record.mode is ExportMode.BURN_IN
    assert result.export_record.output_path.read_bytes() == b"exported video"
    assert projects.get_by_id(project.project_id).export_mode is ExportMode.BURN_IN
    assert projects.get_by_id(project.project_id).status is ProjectStatus.COMPLETED
