"""阶段 1 用例契约测试。

这些测试使用内存假实现保护核心用例的输入输出契约，
确保后续接入真实 `FFmpeg`、ASR、翻译器和导出器时，
不需要推翻 `core/` 层已经稳定下来的协议。
"""

from dataclasses import replace
from pathlib import Path

from core.domain.entities import Project, Task
from core.domain.enums import ExportMode, ProjectStatus, TaskCheckpoint, TaskStatus
from core.dto.project_dto import CreateProjectInput
from core.dto.subtitle_dto import (
    SubtitleSegmentDTO,
    TranscribeVideoInput,
    TranslateSubtitlesInput,
)
from core.dto.task_dto import ExportRecordDTO, ExportVideoInput
from core.services.task_service import TaskService
from core.usecases.create_project import CreateProject
from core.usecases.export_video import ExportVideo
from core.usecases.transcribe_video import TranscribeVideo
from core.usecases.translate_subtitles import TranslateSubtitles


class InMemoryProjectRepository:
    """用内存字典模拟项目仓储。"""

    def __init__(self) -> None:
        self.projects: dict[str, Project] = {}

    def save(self, project: Project) -> Project:
        self.projects[project.project_id] = project
        return project

    def get_by_id(self, project_id: str) -> Project | None:
        return self.projects.get(project_id)


class InMemoryTaskRepository:
    """用内存字典模拟任务仓储。"""

    def __init__(self) -> None:
        self.tasks: dict[str, Task] = {}

    def save(self, task: Task) -> Task:
        self.tasks[task.task_id] = task
        return task

    def get_by_id(self, task_id: str) -> Task | None:
        return self.tasks.get(task_id)


class InMemorySubtitleRepository:
    """用内存结构模拟字幕仓储。"""

    def __init__(self) -> None:
        self.source_segments: dict[str, list[SubtitleSegmentDTO]] = {}
        self.translated_segments: dict[tuple[str, str], list[SubtitleSegmentDTO]] = {}

    def save_source_segments(
        self,
        project_id: str,
        segments: list[SubtitleSegmentDTO],
    ) -> list[SubtitleSegmentDTO]:
        self.source_segments[project_id] = list(segments)
        return list(segments)

    def get_source_segments(self, project_id: str) -> list[SubtitleSegmentDTO]:
        return list(self.source_segments.get(project_id, []))

    def save_translated_segments(
        self,
        project_id: str,
        target_language: str,
        segments: list[SubtitleSegmentDTO],
    ) -> list[SubtitleSegmentDTO]:
        self.translated_segments[(project_id, target_language)] = list(segments)
        return list(segments)

    def get_translated_segments(
        self,
        project_id: str,
        target_language: str,
    ) -> list[SubtitleSegmentDTO]:
        return list(self.translated_segments.get((project_id, target_language), []))


class InMemoryExportRecordRepository:
    """用内存列表模拟导出记录仓储。"""

    def __init__(self) -> None:
        self.records: list[ExportRecordDTO] = []

    def save(self, record: ExportRecordDTO) -> ExportRecordDTO:
        self.records.append(record)
        return record

    def get_latest_by_project(self, project_id: str) -> ExportRecordDTO | None:
        for record in reversed(self.records):
            if record.project_id == project_id:
                return record
        return None


class RecordingTaskEventPublisher:
    """记录任务快照发布次数，方便测试编排层有没有对外发出状态变化。"""

    def __init__(self) -> None:
        self.published: list[Task] = []

    def publish(self, task: Task) -> None:
        self.published.append(task)


class RecordingAsrEngine:
    """记录识别调用参数，并返回预设字幕片段。"""

    def __init__(self, segments: list[SubtitleSegmentDTO]) -> None:
        self.segments = segments
        self.calls: list[tuple[Path, str | None]] = []

    def transcribe(self, audio_path: Path, language: str | None = None) -> list[SubtitleSegmentDTO]:
        self.calls.append((audio_path, language))
        return list(self.segments)


class RecordingTranslator:
    """记录翻译调用参数，并把语言字段替换成目标语言。"""

    def __init__(self) -> None:
        self.calls: list[tuple[list[SubtitleSegmentDTO], str, str, str | None]] = []

    def translate_segments(
        self,
        segments: list[SubtitleSegmentDTO],
        source_language: str,
        target_language: str,
        context: str | None = None,
    ) -> list[SubtitleSegmentDTO]:
        self.calls.append((list(segments), source_language, target_language, context))
        return [
            replace(segment, text=f"{segment.text}-translated", language=target_language)
            for segment in segments
        ]


class RecordingVideoExporter:
    """记录导出请求，并返回预设导出记录。"""

    def __init__(self) -> None:
        self.calls: list[ExportVideoInput] = []

    def export(self, request: ExportVideoInput) -> ExportRecordDTO:
        self.calls.append(request)
        return ExportRecordDTO(
            project_id=request.project_id,
            source_video=request.source_video,
            subtitle_path=request.subtitle_path,
            output_path=request.output_path,
            mode=request.mode,
        )


def _seed_project(tmp_path: Path) -> Project:
    """创建一个供多个测试复用的项目实体。"""

    project = Project(
        project_id="project-1",
        source_video=tmp_path / "source.mp4",
        source_language="ja-JP",
        target_language="zh-CN",
        workspace_dir=tmp_path / "workspace",
    )
    project.mark_imported()
    return project


def _build_segments() -> list[SubtitleSegmentDTO]:
    """构造一组最小字幕片段。"""

    return [
        SubtitleSegmentDTO(
            segment_id="seg-1",
            start_ms=0,
            end_ms=1200,
            text="hello",
            language="ja-JP",
        ),
        SubtitleSegmentDTO(
            segment_id="seg-2",
            start_ms=1200,
            end_ms=2400,
            text="world",
            language="ja-JP",
        ),
    ]


def test_create_project_generates_project_and_initial_task(tmp_path):
    """`CreateProject` 应生成项目实体和已完成的初始化任务快照。"""

    # arrange：准备仓储和用例实例。
    projects = InMemoryProjectRepository()
    tasks = InMemoryTaskRepository()
    publisher = RecordingTaskEventPublisher()
    usecase = CreateProject(
        project_repository=projects,
        task_repository=tasks,
        event_publisher=publisher,
    )

    # act：执行创建项目用例。
    result = usecase.execute(
        CreateProjectInput(
            source_video=tmp_path / "movie.mp4",
            source_language="auto",
            target_language="zh-CN",
            workspace_dir=tmp_path / "workspace",
        )
    )

    # assert：项目应进入已导入状态，并留下一个已完成的初始化任务。
    assert result.project.status is ProjectStatus.IMPORTED
    assert result.task.status is TaskStatus.SUCCEEDED
    assert result.task.checkpoint is TaskCheckpoint.IMPORTED
    assert result.task.progress == 100
    assert projects.get_by_id(result.project.project_id) is not None
    assert tasks.get_by_id(result.task.task_id) is not None
    assert publisher.published[-1].status is TaskStatus.SUCCEEDED


def test_transcribe_video_calls_asr_and_saves_source_segments(tmp_path):
    """`TranscribeVideo` 应调用 ASR 端口，并把原文字幕写入仓储。"""

    # arrange：准备项目、字幕仓储和录制型 ASR 假实现。
    projects = InMemoryProjectRepository()
    tasks = InMemoryTaskRepository()
    subtitles = InMemorySubtitleRepository()
    publisher = RecordingTaskEventPublisher()
    segments = _build_segments()
    engine = RecordingAsrEngine(segments=segments)
    project = _seed_project(tmp_path)
    projects.save(project)

    usecase = TranscribeVideo(
        project_repository=projects,
        task_repository=tasks,
        subtitle_repository=subtitles,
        asr_engine=engine,
        event_publisher=publisher,
    )

    # act：执行识别用例。
    result = usecase.execute(
        TranscribeVideoInput(
            project_id=project.project_id,
            audio_path=tmp_path / "audio.wav",
            language="ja-JP",
        )
    )

    # assert：ASR 收到的是音频路径和语言，结果会落到原文字幕仓储中。
    assert engine.calls == [(tmp_path / "audio.wav", "ja-JP")]
    assert result.task.status is TaskStatus.SUCCEEDED
    assert result.task.checkpoint is TaskCheckpoint.TRANSCRIBED
    assert subtitles.get_source_segments(project.project_id) == segments
    assert result.source_segments == segments
    assert publisher.published[-1].checkpoint is TaskCheckpoint.TRANSCRIBED


def test_translate_subtitles_only_sends_text_segments_and_language_info(tmp_path):
    """`TranslateSubtitles` 只应把字幕文本和语言信息交给翻译端口。"""

    # arrange：准备源字幕和翻译假实现。
    projects = InMemoryProjectRepository()
    tasks = InMemoryTaskRepository()
    subtitles = InMemorySubtitleRepository()
    publisher = RecordingTaskEventPublisher()
    translator = RecordingTranslator()
    project = _seed_project(tmp_path)
    segments = _build_segments()
    projects.save(project)
    subtitles.save_source_segments(project.project_id, segments)

    usecase = TranslateSubtitles(
        project_repository=projects,
        task_repository=tasks,
        subtitle_repository=subtitles,
        translator=translator,
        event_publisher=publisher,
    )

    # act：执行翻译用例。
    result = usecase.execute(
        TranslateSubtitlesInput(
            project_id=project.project_id,
            source_language="ja-JP",
            target_language="zh-CN",
            context="动画对白",
        )
    )

    # assert：翻译器收到的是字幕片段集合和语言信息，而不是媒体文件路径。
    translated_call = translator.calls[-1]
    assert [segment.text for segment in translated_call[0]] == ["hello", "world"]
    assert translated_call[1:] == ("ja-JP", "zh-CN", "动画对白")
    assert result.task.status is TaskStatus.SUCCEEDED
    assert result.task.checkpoint is TaskCheckpoint.TRANSLATED
    assert all(segment.language == "zh-CN" for segment in result.translated_segments)
    assert subtitles.get_translated_segments(project.project_id, "zh-CN") == result.translated_segments


def test_export_video_builds_export_request_and_returns_record(tmp_path):
    """`ExportVideo` 应用项目信息组装导出请求，并保存导出记录。"""

    # arrange：准备项目和导出器假实现。
    projects = InMemoryProjectRepository()
    tasks = InMemoryTaskRepository()
    exports = InMemoryExportRecordRepository()
    publisher = RecordingTaskEventPublisher()
    exporter = RecordingVideoExporter()
    project = _seed_project(tmp_path)
    projects.save(project)

    usecase = ExportVideo(
        project_repository=projects,
        task_repository=tasks,
        export_record_repository=exports,
        exporter=exporter,
        event_publisher=publisher,
    )

    # act：执行导出用例。
    result = usecase.execute(
        ExportVideoInput(
            project_id=project.project_id,
            source_video=project.source_video,
            subtitle_path=tmp_path / "subtitles.srt",
            output_path=tmp_path / "movie_with_subtitles.mp4",
            mode=ExportMode.SOFT_SUBTITLE,
        )
    )

    # assert：导出请求应包含项目与导出路径，导出完成后项目进入完成状态。
    request = exporter.calls[-1]
    assert request.project_id == project.project_id
    assert request.source_video == project.source_video
    assert request.subtitle_path == tmp_path / "subtitles.srt"
    assert request.output_path == tmp_path / "movie_with_subtitles.mp4"
    assert request.mode is ExportMode.SOFT_SUBTITLE
    assert result.task.status is TaskStatus.SUCCEEDED
    assert result.task.checkpoint is TaskCheckpoint.EXPORTED
    assert result.project.status is ProjectStatus.COMPLETED
    assert exports.get_latest_by_project(project.project_id) == result.export_record


def test_task_service_uses_latest_task_snapshot_for_summary(tmp_path):
    """`TaskService` 应把最近一次任务快照转成给界面层展示的摘要。"""

    # arrange：用真实用例和内存假实现组装一个最小服务。
    projects = InMemoryProjectRepository()
    tasks = InMemoryTaskRepository()
    subtitles = InMemorySubtitleRepository()
    exports = InMemoryExportRecordRepository()
    publisher = RecordingTaskEventPublisher()
    segments = _build_segments()

    service = TaskService(
        create_project_usecase=CreateProject(
            project_repository=projects,
            task_repository=tasks,
            event_publisher=publisher,
        ),
        transcribe_video_usecase=TranscribeVideo(
            project_repository=projects,
            task_repository=tasks,
            subtitle_repository=subtitles,
            asr_engine=RecordingAsrEngine(segments),
            event_publisher=publisher,
        ),
        translate_subtitles_usecase=TranslateSubtitles(
            project_repository=projects,
            task_repository=tasks,
            subtitle_repository=subtitles,
            translator=RecordingTranslator(),
            event_publisher=publisher,
        ),
        export_video_usecase=ExportVideo(
            project_repository=projects,
            task_repository=tasks,
            export_record_repository=exports,
            exporter=RecordingVideoExporter(),
            event_publisher=publisher,
        ),
    )

    # act：执行一次项目创建，让服务内部记录最近任务快照。
    result = service.create_project(
        CreateProjectInput(
            source_video=tmp_path / "movie.mp4",
            source_language="auto",
            target_language="zh-CN",
            workspace_dir=tmp_path / "workspace",
        )
    )

    # assert：状态摘要应来自最近一次任务结果，而不是旧的手工字符串。
    summary = service.summary()
    assert result.task.task_type in summary
    assert "100%" in summary
    assert "项目已导入" in summary
