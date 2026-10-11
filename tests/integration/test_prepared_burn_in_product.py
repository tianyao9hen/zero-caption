"""烧录成品预生成与下载复用测试。

需求背景：用户选择烧录字幕时，成品应该在“创建任务”这一步就在任务目录里
烧好，等下载时只需要把文件复制出去；只有译文被改动过之后，下一次下载才
真正重新编码。这里用轻量替身验证这条链路，不依赖真实 `FFmpeg`。
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from core.domain.entities import Project
from core.domain.enums import ExportMode, ProjectStatus
from core.dto.media_dto import AudioStreamDTO, MediaProbeResultDTO, VideoStreamDTO
from core.dto.pipeline_dto import ProcessVideoInput
from core.dto.subtitle_dto import SubtitleSegmentDTO
from core.dto.task_dto import (
    ExportRecordDTO,
    ReexportProjectInput,
)
from core.services.task_service import TaskService
from core.usecases.create_project import CreateProject
from core.usecases.export_video import ExportVideo
from core.usecases.reexport_project import ReexportProject
from core.usecases.transcribe_video import TranscribeVideo
from core.usecases.translate_subtitles import TranslateSubtitles
from infrastructure.export.composite_exporter import CompositeVideoExporter
from infrastructure.export.prepared_video_exporter import PreparedVideoExporter
from infrastructure.storage.fingerprint import Sha256FileFingerprintCalculator
from infrastructure.storage.memory_repositories import (
    InMemoryExportRecordRepository,
    InMemoryProjectRepository,
    InMemorySubtitleRepository,
    InMemoryTaskRepository,
)
from infrastructure.storage.workspace import WorkspaceManager
from infrastructure.subtitle.aligner import SubtitleAligner
from infrastructure.subtitle.formatter import SubtitleFormatter
from infrastructure.subtitle.srt_writer import SrtWriter


class RecordingBurnInExporter:
    """模拟耗时烧录：把源视频内容“重新编码”为成品，并记录调用次数。"""

    def __init__(self) -> None:
        self.call_count = 0
        self.requests = []

    def export(self, request):
        """写出成品并返回导出记录。"""

        self.call_count += 1
        self.requests.append(request)
        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        request.output_path.write_bytes(
            f"burned:{request.subtitle_path.read_text(encoding='utf-8')}".encode(
                "utf-8"
            )
        )
        return ExportRecordDTO(
            project_id=request.project_id,
            source_video=request.source_video,
            subtitle_path=request.subtitle_path,
            output_path=request.output_path,
            mode=request.mode,
        )


def _build_project(tmp_path: Path) -> Project:
    """创建一个已完成翻译的项目，含两条原文和对应译文。"""

    source_video = tmp_path / "lesson.mp4"
    source_video.write_bytes(b"source video")
    project = Project(
        project_id="project-burn-in",
        source_video=source_video,
        source_language="en",
        target_language="zh-CN",
        workspace_dir=tmp_path / "project-burn-in",
    )
    project.mark_completed()
    return project


def _save_translation(
    subtitles: InMemorySubtitleRepository,
    project: Project,
    second_text: str = "世界",
) -> None:
    """写入两条原文和指定译文，便于构造“译文被改动”的场景。"""

    subtitles.save_source_segments(
        project.project_id,
        [
            SubtitleSegmentDTO("segment-1", 0, 1_000, "hello", "en"),
            SubtitleSegmentDTO("segment-2", 1_000, 2_000, "world", "en"),
        ],
    )
    subtitles.save_translated_segments(
        project.project_id,
        project.target_language,
        [
            SubtitleSegmentDTO("segment-1", 0, 1_000, "你好", "zh-CN"),
            SubtitleSegmentDTO("segment-2", 1_000, 2_000, second_text, "zh-CN"),
        ],
    )


def _build_usecase(
    tmp_path: Path,
    burn_in_exporter: RecordingBurnInExporter,
):
    """装配项目仓储、字幕仓储和完整导出链路。"""

    projects = InMemoryProjectRepository()
    tasks = InMemoryTaskRepository()
    subtitles = InMemorySubtitleRepository()
    exports = InMemoryExportRecordRepository()
    project = _build_project(tmp_path)
    projects.save(project)
    _save_translation(subtitles, project)
    export_video = ExportVideo(
        project_repository=projects,
        task_repository=tasks,
        export_record_repository=exports,
        exporter=CompositeVideoExporter(
            exporters={ExportMode.BURN_IN: burn_in_exporter},
            prepared_exporter=PreparedVideoExporter(),
        ),
    )
    usecase = ReexportProject(
        project_repository=projects,
        subtitle_repository=subtitles,
        subtitle_writer=SrtWriter(),
        export_video=export_video,
    )
    return projects, tasks, project, usecase


def test_prepare_project_product_burns_video_into_workspace(tmp_path) -> None:
    """预生成应把成品写进项目自己的 exports 目录，并登记到项目记录。"""

    # arrange：一个刚完成翻译、还没有下载过任何东西的项目。
    burn_in_exporter = RecordingBurnInExporter()
    projects, _tasks, project, usecase = _build_usecase(tmp_path, burn_in_exporter)

    # act：执行任务创建流程内部的预生成动作。
    result = usecase.execute(
        ReexportProjectInput(
            project_id=project.project_id,
            mode=ExportMode.BURN_IN,
            prepare_project_product=True,
        )
    )

    # assert：成品落在项目目录里，路径后缀和职责都清楚。
    prepared_path = Path(
        project.workspace_dir / "exports" / "lesson-烧录成品.mp4"
    )
    assert prepared_path.is_file()
    assert burn_in_exporter.call_count == 1
    assert burn_in_exporter.requests[0].prepared_source_path is None
    stored_project = projects.get_by_id(project.project_id)
    assert stored_project.prepared_output_path == prepared_path
    assert stored_project.prepared_translation_signature
    # 预生成不是一次用户下载，因此用户可见的最近成品路径仍然为空。
    assert stored_project.output_path is None
    assert result.task.task_type == "prepare_product"
    assert result.task.current_step == "成品已就绪"


def test_download_reuses_prepared_product_without_reencoding(tmp_path) -> None:
    """已有新鲜成品时，下载只应复制文件，不再调用烧录器。"""

    burn_in_exporter = RecordingBurnInExporter()
    _projects, _tasks, project, usecase = _build_usecase(tmp_path, burn_in_exporter)
    usecase.execute(
        ReexportProjectInput(
            project_id=project.project_id,
            mode=ExportMode.BURN_IN,
            prepare_project_product=True,
        )
    )
    assert burn_in_exporter.call_count == 1

    # act：用户选择了一个外部目录下载成品。
    selected_output = tmp_path / "chosen-results" / "lesson-final.mp4"
    result = usecase.execute(
        ReexportProjectInput(
            project_id=project.project_id,
            mode=ExportMode.BURN_IN,
            output_path=selected_output,
        )
    )

    # assert：烧录器没有被再次调用，内容与预生成结果一致。
    assert burn_in_exporter.call_count == 1
    assert selected_output.is_file()
    prepared_path = Path(
        project.workspace_dir / "exports" / "lesson-烧录成品.mp4"
    )
    assert selected_output.read_bytes() == prepared_path.read_bytes()
    assert result.export_record.output_path == selected_output
    assert result.task.task_type == "export_video"


def test_download_regenerates_after_subtitle_is_edited(tmp_path) -> None:
    """用户改过译文之后，下载必须重新烧录，不能交付旧硬字幕。"""

    burn_in_exporter = RecordingBurnInExporter()
    projects, _tasks, project, usecase = _build_usecase(tmp_path, burn_in_exporter)
    usecase.execute(
        ReexportProjectInput(
            project_id=project.project_id,
            mode=ExportMode.BURN_IN,
            prepare_project_product=True,
        )
    )
    # act：模拟单句修订，然后再次下载。
    second_translation = _translation_repository(usecase)
    _save_translation(second_translation, project, second_text="人工校对后的世界")
    selected_output = tmp_path / "chosen-results" / "lesson-final.mp4"
    usecase.execute(
        ReexportProjectInput(
            project_id=project.project_id,
            mode=ExportMode.BURN_IN,
            output_path=selected_output,
        )
    )

    # assert：旧成品已经失效，这次真正重新烧录了一遍。
    assert burn_in_exporter.call_count == 2
    assert selected_output.is_file()
    prepared_path = Path(
        project.workspace_dir / "exports" / "lesson-烧录成品.mp4"
    )
    # 先用当前译文生成内部成品，再复制给用户，因此两份文件都应采用新译文。
    assert "人工校对后的世界" in selected_output.read_text(encoding="utf-8")
    assert "人工校对后的世界" in prepared_path.read_text(encoding="utf-8")
    assert projects.get_by_id(project.project_id).output_path == selected_output

    # 再次下载时不应重复烧录：前面的重烧已经顺带刷新了内部成品。
    second_output = tmp_path / "chosen-results" / "lesson-final-2.mp4"
    usecase.execute(
        ReexportProjectInput(
            project_id=project.project_id,
            mode=ExportMode.BURN_IN,
            output_path=second_output,
        )
    )
    assert burn_in_exporter.call_count == 2
    assert second_output.read_bytes() == selected_output.read_bytes()


def _translation_repository(usecase: ReexportProject):
    """取出用例的字幕仓储，方便直接写入“修订后的译文”。"""

    return usecase.subtitle_repository


def test_has_prepared_product_reflects_missing_and_stale_product(tmp_path) -> None:
    """成品被删除或译文变化后，应判定为不可直接复用。"""

    burn_in_exporter = RecordingBurnInExporter()
    projects, _tasks, project, usecase = _build_usecase(tmp_path, burn_in_exporter)
    assert usecase.has_prepared_product(project.project_id) is False

    usecase.execute(
        ReexportProjectInput(
            project_id=project.project_id,
            mode=ExportMode.BURN_IN,
            prepare_project_product=True,
        )
    )
    assert usecase.has_prepared_product(project.project_id) is True

    # 用户手工清理了项目目录里的成品文件。
    prepared_path = projects.get_by_id(project.project_id).prepared_output_path
    prepared_path.unlink()
    assert usecase.has_prepared_product(project.project_id) is False

    # 成品重新生成后，用户又修改了一条译文。
    usecase.execute(
        ReexportProjectInput(
            project_id=project.project_id,
            mode=ExportMode.BURN_IN,
            prepare_project_product=True,
        )
    )
    assert usecase.has_prepared_product(project.project_id) is True
    _save_translation(
        usecase.subtitle_repository,
        project,
        second_text="再次修订的世界",
    )
    assert usecase.has_prepared_product(project.project_id) is False


def test_prepare_failure_keeps_user_download_path(tmp_path) -> None:
    """预生成失败时，不应把用户上次选择的下载目录改成内部路径。"""

    projects = InMemoryProjectRepository()
    tasks = InMemoryTaskRepository()
    subtitles = InMemorySubtitleRepository()
    exports = InMemoryExportRecordRepository()
    source_video = tmp_path / "broken.mp4"
    source_video.write_bytes(b"source video")
    previous_download = tmp_path / "old-results" / "broken.mp4"
    project = Project(
        project_id="project-prepare-fail",
        source_video=source_video,
        source_language="en",
        target_language="zh-CN",
        workspace_dir=tmp_path / "project-prepare-fail",
        output_path=previous_download,
    )
    project.mark_completed()
    projects.save(project)
    _save_translation(subtitles, project)
    usecase = ReexportProject(
        project_repository=projects,
        subtitle_repository=subtitles,
        subtitle_writer=SrtWriter(),
        export_video=ExportVideo(
            project_repository=projects,
            task_repository=tasks,
            export_record_repository=exports,
            exporter=CompositeVideoExporter(
                exporters={ExportMode.BURN_IN: FailingExporter()},
                prepared_exporter=PreparedVideoExporter(),
            ),
        ),
    )

    try:
        usecase.execute(
            ReexportProjectInput(
                project_id=project.project_id,
                mode=ExportMode.BURN_IN,
                prepare_project_product=True,
            )
        )
    except OSError:
        pass
    else:  # pragma: no cover - 导出器必然失败，走到这里说明异常被吞掉了
        raise AssertionError("预生成失败时应把异常继续抛给调用方。")

    stored_project = projects.get_by_id(project.project_id)
    assert stored_project.output_path == previous_download
    assert stored_project.prepared_output_path is None
    assert stored_project.status is ProjectStatus.FAILED


def test_process_video_prepares_burn_in_product_at_creation(tmp_path) -> None:
    """选择烧录字幕时，创建任务流程本身就应该把成品做出来。"""

    # arrange：完整主链路只替换掉真实 ASR、翻译和 FFmpeg。
    workspace = WorkspaceManager(tmp_path / "workspace")
    projects = InMemoryProjectRepository()
    tasks = InMemoryTaskRepository()
    subtitles = InMemorySubtitleRepository()
    exports = InMemoryExportRecordRepository()
    burn_in_exporter = RecordingBurnInExporter()
    source_video = tmp_path / "demo.mp4"
    source_video.write_bytes(b"fake video")
    export_video = ExportVideo(
        project_repository=projects,
        task_repository=tasks,
        export_record_repository=exports,
        exporter=CompositeVideoExporter(
            exporters={ExportMode.BURN_IN: burn_in_exporter},
            prepared_exporter=PreparedVideoExporter(),
        ),
    )
    service = TaskService(
        create_project_usecase=CreateProject(
            project_repository=projects,
            task_repository=tasks,
            project_workspace=workspace,
            fingerprint_calculator=Sha256FileFingerprintCalculator(),
        ),
        transcribe_video_usecase=TranscribeVideo(
            project_repository=projects,
            task_repository=tasks,
            subtitle_repository=subtitles,
            media_probe=FakeMediaProbe(),
            audio_extractor=FakeAudioExtractor(),
            asr_engine=FakeAsrEngine(),
            subtitle_formatter=SubtitleFormatter(),
            subtitle_aligner=SubtitleAligner(),
            srt_writer=SrtWriter(),
        ),
        translate_subtitles_usecase=TranslateSubtitles(
            project_repository=projects,
            task_repository=tasks,
            subtitle_repository=subtitles,
            translator=FakeTranslator(),
            subtitle_writer=SrtWriter(),
        ),
        reexport_project_usecase=ReexportProject(
            project_repository=projects,
            subtitle_repository=subtitles,
            subtitle_writer=SrtWriter(),
            export_video=export_video,
        ),
        project_repository=projects,
    )

    # act：只提交一次创建任务请求，不额外调用下载。
    result = service.process_video(
        ProcessVideoInput(
            source_video=source_video,
            source_language="en",
            target_language="zh-CN",
            workspace_dir=workspace.root,
            export_mode=ExportMode.BURN_IN,
        )
    )

    # assert：流程结束时，成品已经躺在任务目录里等待下载。
    assert burn_in_exporter.call_count == 1
    assert result.export is not None
    prepared_path = Path(result.export.export_record.output_path)
    assert prepared_path.is_file()
    assert prepared_path.parent == (
        result.final_project.workspace_dir / "exports"
    )
    assert result.final_project.prepared_output_path == prepared_path
    assert result.final_project.status is ProjectStatus.COMPLETED
    # 用户还没有选择过下载目录，因此用户可见路径保持为空。
    assert result.final_project.output_path is None


def test_process_video_keeps_subtitles_when_burn_in_fails(tmp_path) -> None:
    """预生成失败不应推翻已经完成的字幕结果。"""

    projects = InMemoryProjectRepository()
    tasks = InMemoryTaskRepository()
    subtitles = InMemorySubtitleRepository()
    exports = InMemoryExportRecordRepository()
    workspace = WorkspaceManager(tmp_path / "workspace")
    source_video = tmp_path / "demo.mp4"
    source_video.write_bytes(b"fake video")
    service = TaskService(
        create_project_usecase=CreateProject(
            project_repository=projects,
            task_repository=tasks,
            project_workspace=workspace,
            fingerprint_calculator=Sha256FileFingerprintCalculator(),
        ),
        transcribe_video_usecase=TranscribeVideo(
            project_repository=projects,
            task_repository=tasks,
            subtitle_repository=subtitles,
            media_probe=FakeMediaProbe(),
            audio_extractor=FakeAudioExtractor(),
            asr_engine=FakeAsrEngine(),
            subtitle_formatter=SubtitleFormatter(),
            subtitle_aligner=SubtitleAligner(),
            srt_writer=SrtWriter(),
        ),
        translate_subtitles_usecase=TranslateSubtitles(
            project_repository=projects,
            task_repository=tasks,
            subtitle_repository=subtitles,
            translator=FakeTranslator(),
            subtitle_writer=SrtWriter(),
        ),
        reexport_project_usecase=ReexportProject(
            project_repository=projects,
            subtitle_repository=subtitles,
            subtitle_writer=SrtWriter(),
            export_video=ExportVideo(
                project_repository=projects,
                task_repository=tasks,
                export_record_repository=exports,
                exporter=CompositeVideoExporter(
                    exporters={ExportMode.BURN_IN: FailingExporter()},
                    prepared_exporter=PreparedVideoExporter(),
                ),
            ),
        ),
        project_repository=projects,
    )

    result = service.process_video(
        ProcessVideoInput(
            source_video=source_video,
            source_language="en",
            target_language="zh-CN",
            workspace_dir=workspace.root,
            export_mode=ExportMode.BURN_IN,
        )
    )

    # assert：字幕仍然可用，项目保持在完成态，失败原因写进备注。
    assert result.translation is not None
    assert result.translation.subtitle_path.is_file()
    assert result.export is None
    assert result.final_project.status is ProjectStatus.COMPLETED
    assert "成品预生成失败" in result.final_project.last_error
    assert result.final_project.prepared_output_path is None
    assert result.final_project.output_path is None


class FakeMediaProbe:
    """返回固定媒体信息，避免测试依赖真实编码格式。"""

    def probe(self, source_path: Path) -> MediaProbeResultDTO:
        """返回带视频流和音频流的最小探测结果。"""

        return MediaProbeResultDTO(
            source_path=source_path,
            duration_ms=2_000,
            video_stream=VideoStreamDTO("h264", 1280, 720),
            audio_streams=[AudioStreamDTO("aac", 48_000, 2)],
        )


class FakeAudioExtractor:
    """用占位字节模拟音频抽取产物。"""

    def extract_audio(self, source_path: Path, output_path: Path) -> Path:
        """在项目临时目录写入占位音频文件。"""

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fake wav")
        return output_path


class FakeAsrEngine:
    """返回固定原文字幕，避免测试下载本地模型。"""

    def transcribe(
        self,
        audio_path: Path,
        language: str | None = None,
    ) -> list[SubtitleSegmentDTO]:
        """生成两条连续的原文字幕。"""

        return [
            SubtitleSegmentDTO("seg-1", 0, 1_000, "hello", language or "en"),
            SubtitleSegmentDTO("seg-2", 1_000, 2_000, "world", language or "en"),
        ]


class FakeTranslator:
    """把原文改成固定译文，让后续烧录有确定内容。"""

    def translate_segments(
        self,
        segments: list[SubtitleSegmentDTO],
        source_language: str,
        target_language: str,
        context: str | None = None,
    ) -> list[SubtitleSegmentDTO]:
        """返回保持时间轴不变的目标语言字幕。"""

        translated_texts = {"hello": "你好", "world": "世界"}
        return [
            replace(
                segment,
                text=translated_texts[segment.text],
                language=target_language,
            )
            for segment in segments
        ]


class FailingExporter:
    """模拟烧录在写盘阶段失败。"""

    def export(self, request):
        """直接抛出磁盘写入异常。"""

        raise OSError("FFmpeg 烧录失败")
