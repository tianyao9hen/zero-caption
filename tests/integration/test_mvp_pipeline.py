"""无界面 MVP 主链路集成测试。

测试用轻量适配器替代真实模型和网络服务，验证四个核心用例可以通过
`TaskService` 串成“导入 -> 识别 -> 翻译”的自动流程，视频下载单独验证。
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from core.domain.enums import (
    ExportMode,
    ProcessingMode,
    ProjectStatus,
    TaskCheckpoint,
)
from core.dto.media_dto import AudioStreamDTO, MediaProbeResultDTO, VideoStreamDTO
from core.dto.project_dto import CreateProjectInput
from core.dto.pipeline_dto import ProcessVideoInput
from core.dto.subtitle_dto import (
    SubtitleSegmentDTO,
    TranscribeVideoInput,
    TranslateSubtitlesInput,
)
from core.dto.task_dto import ExportVideoInput
from core.services.task_service import TaskService
from core.usecases.create_project import CreateProject
from core.usecases.export_video import ExportVideo
from core.usecases.transcribe_video import TranscribeVideo
from core.usecases.translate_subtitles import TranslateSubtitles
from infrastructure.export.soft_subtitle_exporter import SoftSubtitleExporter
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

    def __init__(self) -> None:
        self.call_count = 0

    def extract_audio(self, source_path: Path, output_path: Path) -> Path:
        """在项目临时目录写入占位音频文件。"""

        self.call_count += 1
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fake wav")
        return output_path


class FakeAsrEngine:
    """返回固定原文字幕，避免测试下载本地模型。"""

    def __init__(self) -> None:
        self.call_count = 0

    def transcribe(
        self,
        audio_path: Path,
        language: str | None = None,
    ) -> list[SubtitleSegmentDTO]:
        """生成两条连续的原文字幕。"""

        self.call_count += 1
        return [
            SubtitleSegmentDTO("seg-1", 0, 1_000, "hello", language or "en"),
            SubtitleSegmentDTO("seg-2", 1_000, 2_000, "world", language or "en"),
        ]


class FakeTranslator:
    """把原文改成固定译文，并记录调用次数用于缓存断言。"""

    def __init__(self) -> None:
        self.call_count = 0

    def translate_segments(
        self,
        segments: list[SubtitleSegmentDTO],
        source_language: str,
        target_language: str,
        context: str | None = None,
    ) -> list[SubtitleSegmentDTO]:
        """返回保持时间轴不变的目标语言字幕。"""

        self.call_count += 1
        translated_texts = {"hello": "你好", "world": "世界"}
        return [
            replace(
                segment,
                text=translated_texts[segment.text],
                language=target_language,
            )
            for segment in segments
        ]


class FailingSecondOnceTranslator(FakeTranslator):
    """第一次处理第二条字幕时失败，随后恢复为正常翻译器。"""

    def __init__(self) -> None:
        super().__init__()
        self.failed_once = False

    def translate_segments(
        self,
        segments: list[SubtitleSegmentDTO],
        source_language: str,
        target_language: str,
        context: str | None = None,
    ) -> list[SubtitleSegmentDTO]:
        """记录失败调用，使重试测试可以区分首次和恢复后的请求。"""

        if self.call_count == 1 and not self.failed_once:
            self.call_count += 1
            self.failed_once = True
            raise RuntimeError("模拟第二条字幕翻译失败")
        return super().translate_segments(
            segments,
            source_language,
            target_language,
            context,
        )


def test_task_service_runs_complete_mvp_pipeline_and_reuses_translation(tmp_path) -> None:
    """四个用例应生成原文、译文、视频副本和外挂字幕，并复用译文缓存。"""

    # arrange：所有仓储由同一个服务共享，模拟应用进程内的真实装配方式。
    workspace = WorkspaceManager(tmp_path / "workspace")
    projects = InMemoryProjectRepository()
    tasks = InMemoryTaskRepository()
    subtitles = InMemorySubtitleRepository()
    exports = InMemoryExportRecordRepository()
    translator = FakeTranslator()
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
            translator=translator,
            subtitle_writer=SrtWriter(),
        ),
        export_video_usecase=ExportVideo(
            project_repository=projects,
            task_repository=tasks,
            export_record_repository=exports,
            exporter=SoftSubtitleExporter(),
        ),
    )

    # act：依次执行四个显式动作，保持和未来桌面 UI 的交互模型一致。
    created = service.create_project(
        CreateProjectInput(source_video, "en", "zh-CN", workspace.root)
    )
    transcribed = service.transcribe_video(
        TranscribeVideoInput(project_id=created.project.project_id)
    )
    translation_request = TranslateSubtitlesInput(
        project_id=created.project.project_id,
        source_language="en",
        target_language="zh-CN",
    )
    translated = service.translate_subtitles(translation_request)
    cached_translation = service.translate_subtitles(translation_request)
    output_video = created.project.workspace_dir / "exports" / "demo.mp4"
    exported = service.export_video(
        ExportVideoInput(
            project_id=created.project.project_id,
            source_video=source_video,
            subtitle_path=translated.subtitle_path,
            output_path=output_video,
            mode=ExportMode.SOFT_SUBTITLE,
        )
    )

    # assert：先验证正式产物，再验证状态和缓存行为。
    assert transcribed.subtitle_path is not None and transcribed.subtitle_path.is_file()
    assert translated.subtitle_path is not None and translated.subtitle_path.is_file()
    assert "你好" in translated.subtitle_path.read_text(encoding="utf-8")
    assert output_video.read_bytes() == b"fake video"
    assert output_video.with_suffix(".srt").is_file()
    assert translated.task.checkpoint is TaskCheckpoint.TRANSLATED
    assert cached_translation.reused_translation is True
    assert translator.call_count == 2
    assert exported.project.status is ProjectStatus.COMPLETED
    assert exported.task.checkpoint is TaskCheckpoint.EXPORTED


def test_task_service_process_video_stops_after_translation(tmp_path) -> None:
    """完整编排应在翻译完成后结束，等待用户主动下载视频。"""

    # arrange：为服务注入全套伪适配器，避免测试依赖本地模型或网络。
    workspace = WorkspaceManager(tmp_path / "workspace")
    projects = InMemoryProjectRepository()
    tasks = InMemoryTaskRepository()
    subtitles = InMemorySubtitleRepository()
    source_video = tmp_path / "demo.mp4"
    source_video.write_bytes(b"fake video")
    source_content = source_video.read_bytes()

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
        project_repository=projects,
    )

    # act：只调用供 UI 和命令行共用的一站式入口。
    result = service.process_video(
        ProcessVideoInput(
            source_video=source_video,
            source_language="en",
            target_language="zh-CN",
            workspace_dir=workspace.root,
            # 完整流程即使收到旧调用方传来的路径，也不能自动写入用户目录。
            output_path=source_video,
        )
    )

    # assert：翻译结果保存在项目中，外部路径未写入且源视频内容保持不变。
    assert result.project.project.project_id == result.transcription.project_id
    assert result.translation.project_id == result.project.project.project_id
    assert result.export is None
    assert result.final_project.status is ProjectStatus.COMPLETED
    assert result.final_project.output_path is None
    assert source_video.read_bytes() == source_content
    assert result.translation.subtitle_path.is_file()


def test_task_service_can_finish_after_local_transcription_without_translation(
    tmp_path,
) -> None:
    """仅识别模式应生成原文字幕，且不要求装配翻译或视频导出能力。"""

    # arrange：故意不注入翻译和导出用例；若核心编排误入后续步骤，
    # 测试会立即因缺少用例而失败。
    workspace = WorkspaceManager(tmp_path / "workspace")
    projects = InMemoryProjectRepository()
    tasks = InMemoryTaskRepository()
    subtitles = InMemorySubtitleRepository()
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
        project_repository=projects,
    )

    # act：只请求本地生成原文字幕。
    result = service.process_video(
        ProcessVideoInput(
            source_video=source_video,
            source_language="en",
            target_language="zh-CN",
            workspace_dir=workspace.root,
            output_path=tmp_path / "chosen-results" / "demo.srt",
            processing_mode=ProcessingMode.TRANSCRIBE_ONLY,
        )
    )

    # assert：本地音频和字幕均落盘，项目成功结束且没有伪造后续结果。
    assert result.transcription.audio_path is not None
    assert result.transcription.audio_path.is_file()
    assert result.subtitle_path is not None
    assert result.subtitle_path.is_file()
    assert result.subtitle_path == tmp_path / "chosen-results" / "demo.srt"
    assert (
        result.final_project.workspace_dir / "subtitles" / "source.srt"
    ).is_file()
    assert result.translation is None
    assert result.export is None
    assert result.final_project.status is ProjectStatus.COMPLETED


def test_task_service_retries_existing_project_and_reuses_completed_steps(
    tmp_path,
) -> None:
    """翻译中断后继续同一项目时，应复用音频、原字幕和已完成译文。"""

    # arrange：第二条字幕第一次请求会失败，其他适配器记录高成本调用次数。
    workspace = WorkspaceManager(tmp_path / "workspace")
    projects = InMemoryProjectRepository()
    tasks = InMemoryTaskRepository()
    subtitles = InMemorySubtitleRepository()
    exports = InMemoryExportRecordRepository()
    audio_extractor = FakeAudioExtractor()
    asr_engine = FakeAsrEngine()
    translator = FailingSecondOnceTranslator()
    source_video = tmp_path / "retry.mp4"
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
            audio_extractor=audio_extractor,
            asr_engine=asr_engine,
            subtitle_formatter=SubtitleFormatter(),
            subtitle_aligner=SubtitleAligner(),
            srt_writer=SrtWriter(),
        ),
        translate_subtitles_usecase=TranslateSubtitles(
            project_repository=projects,
            task_repository=tasks,
            subtitle_repository=subtitles,
            translator=translator,
            subtitle_writer=SrtWriter(),
        ),
        export_video_usecase=ExportVideo(
            project_repository=projects,
            task_repository=tasks,
            export_record_repository=exports,
            exporter=SoftSubtitleExporter(),
        ),
        project_repository=projects,
        task_repository=tasks,
        subtitle_repository=subtitles,
    )
    request = ProcessVideoInput(
        source_video=source_video,
        source_language="en",
        target_language="zh-CN",
        workspace_dir=workspace.root,
        context="课程术语：world 译为世界",
    )

    # act：首次处理在第二条翻译失败，随后用户显式继续已有项目。
    with pytest.raises(RuntimeError, match="模拟第二条字幕翻译失败"):
        service.process_video(request)
    failed_project = projects.list_all()[0]
    first_project_id = failed_project.project_id
    assert failed_project.translation_context == request.context
    assert len(
        subtitles.get_translated_segments(first_project_id, "zh-CN")
    ) == 1

    result = service.retry_video(first_project_id)

    # assert：项目编号不变，高成本本地步骤只执行一次，模型只补请求缺失第二条。
    assert result.final_project.project_id == first_project_id
    assert result.final_project.status is ProjectStatus.COMPLETED
    assert audio_extractor.call_count == 1
    assert asr_engine.call_count == 1
    assert translator.call_count == 3
    assert result.export is None
    assert result.translation.subtitle_path.is_file()
    history = service.list_video_tasks()
    assert history[0].retry_count == 1
