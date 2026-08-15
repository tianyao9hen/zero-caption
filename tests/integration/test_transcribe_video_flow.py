"""阶段 2 端到端识别链路集成测试。

这个测试文件属于测试层，用来先固定“创建项目 -> 探测 -> 抽音频 -> ASR
-> 生成原文字幕”的期望路径。它不直接调用 UI，也不真实跑 `FFmpeg` 或模型，
而是用轻量假实现记录核心用例应该如何编排这些基础设施能力。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
from uuid import uuid4

import pytest

from core.domain.entities import Project, Task
from core.domain.enums import ProjectStatus, TaskCheckpoint, TaskStatus
from core.dto.media_dto import AudioStreamDTO, MediaProbeResultDTO, VideoStreamDTO
from core.dto.project_dto import CreateProjectInput
from core.dto.subtitle_dto import SubtitleSegmentDTO
from core.usecases.create_project import CreateProject
from core.usecases.transcribe_video import TranscribeVideo
from infrastructure.storage.workspace import WorkspaceManager


class InMemoryProjectRepository:
    """用内存字典模拟项目仓储，避免测试提前依赖 SQLite。"""

    def __init__(self) -> None:
        self.projects: dict[str, Project] = {}

    def save(self, project: Project) -> Project:
        """保存项目快照，并返回同一个实体供用例继续传递。"""

        self.projects[project.project_id] = project
        return project

    def get_by_id(self, project_id: str) -> Project | None:
        """按项目编号读取项目；不存在时返回 `None`。"""

        return self.projects.get(project_id)


class InMemoryTaskRepository:
    """用内存字典记录任务快照，便于断言检查点推进。"""

    def __init__(self) -> None:
        self.tasks: dict[str, Task] = {}

    def save(self, task: Task) -> Task:
        """保存任务快照。

        这里不复制对象，是为了让测试更直接地观察当前用例最后留下的状态。
        真实持久化会在后续阶段由 SQLite 仓储负责。
        """

        self.tasks[task.task_id] = task
        return task

    def get_by_id(self, task_id: str) -> Task | None:
        """按任务编号读取任务；不存在时返回 `None`。"""

        return self.tasks.get(task_id)


class InMemorySubtitleRepository:
    """用内存结构记录原文字幕片段。"""

    def __init__(self) -> None:
        self.source_segments: dict[str, list[SubtitleSegmentDTO]] = {}

    def save_source_segments(
        self,
        project_id: str,
        segments: list[SubtitleSegmentDTO],
    ) -> list[SubtitleSegmentDTO]:
        """保存 ASR 返回的原文字幕片段。"""

        self.source_segments[project_id] = list(segments)
        return list(segments)

    def get_source_segments(self, project_id: str) -> list[SubtitleSegmentDTO]:
        """读取指定项目的原文字幕片段。"""

        return list(self.source_segments.get(project_id, []))

    def save_translated_segments(
        self,
        project_id: str,
        target_language: str,
        segments: list[SubtitleSegmentDTO],
    ) -> list[SubtitleSegmentDTO]:
        """满足仓储端口的翻译字幕方法；阶段 2 不应调用它。"""

        raise AssertionError("阶段 2 识别链路不应该写入翻译字幕。")

    def get_translated_segments(
        self,
        project_id: str,
        target_language: str,
    ) -> list[SubtitleSegmentDTO]:
        """满足仓储端口的翻译字幕读取方法；阶段 2 不应调用它。"""

        raise AssertionError("阶段 2 识别链路不应该读取翻译字幕。")


class RecordingTaskEventPublisher:
    """记录任务事件，保护用例向外发布状态变化的行为。"""

    def __init__(self) -> None:
        self.published: list[Task] = []

    def publish(self, task: Task) -> None:
        """保存发布过的任务快照。"""

        self.published.append(task)


@dataclass(slots=True)
class RecordingMediaProbe:
    """记录媒体探测调用，并返回固定的媒体元数据。"""

    calls: list[Path]

    def probe(self, source_path: Path) -> MediaProbeResultDTO:
        """模拟 `ffprobe` 读取视频基础信息。"""

        self.calls.append(source_path)
        return MediaProbeResultDTO(
            source_path=source_path,
            duration_ms=2_000,
            video_stream=VideoStreamDTO(codec_name="h264", width=1280, height=720),
            audio_streams=[
                AudioStreamDTO(codec_name="aac", sample_rate=48_000, channels=2),
            ],
        )


@dataclass(slots=True)
class RecordingAudioExtractor:
    """记录抽音频调用，并在目标位置写入一个最小占位音频文件。"""

    calls: list[tuple[Path, Path]]

    def extract_audio(self, source_path: Path, output_path: Path) -> Path:
        """模拟 `FFmpeg` 把视频音轨抽到项目级 `temp/` 目录。"""

        self.calls.append((source_path, output_path))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fake wav data")
        return output_path


@dataclass(slots=True)
class RecordingAsrEngine:
    """记录 ASR 调用，并返回预设的原文字幕片段。"""

    calls: list[tuple[Path, str | None]]

    def transcribe(
        self,
        audio_path: Path,
        language: str | None = None,
    ) -> list[SubtitleSegmentDTO]:
        """模拟本地 ASR 输出带时间轴的字幕片段。"""

        self.calls.append((audio_path, language))
        return [
            SubtitleSegmentDTO(
                segment_id="seg-1",
                start_ms=0,
                end_ms=1_000,
                text="第一句原文字幕",
                language=language or "unknown",
            ),
            SubtitleSegmentDTO(
                segment_id="seg-2",
                start_ms=1_000,
                end_ms=2_000,
                text="第二句原文字幕",
                language=language or "unknown",
            ),
        ]

    def runtime_summary(self) -> str:
        """模拟适配器向任务页报告实际运行参数。"""

        return "实际使用 medium + CUDA + float16 完成识别。"


class RecordingSrtWriter:
    """记录 `SRT` 写出调用，并生成可检查的字幕文件。"""

    def __init__(self) -> None:
        self.calls: list[tuple[list[SubtitleSegmentDTO], Path]] = []

    def write_file(
        self,
        segments: list[SubtitleSegmentDTO],
        output_path: str | Path,
    ) -> Path:
        """模拟字幕写出组件把原文字幕落到 `subtitles/source.srt`。"""

        target_path = Path(output_path)
        self.calls.append((list(segments), target_path))
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(
            "1\n"
            "00:00:00,000 --> 00:00:01,000\n"
            "第一句原文字幕\n"
            "\n"
            "2\n"
            "00:00:01,000 --> 00:00:02,000\n"
            "第二句原文字幕\n"
            "\n",
            encoding="utf-8",
        )
        return target_path


def _create_demo_source_video(tmp_path: Path) -> Path:
    """创建一个轻量视频占位文件。

    端到端编排测试只关心路径如何传递，不验证真实编码格式。
    真实媒体处理已经由 `ffprobe`、`FFmpeg` 和 ASR 各自的集成测试覆盖。
    """

    source_video = tmp_path / "input.mp4"
    source_video.write_bytes(b"fake video data")
    return source_video


def _build_create_project_usecase(
    projects: InMemoryProjectRepository,
    tasks: InMemoryTaskRepository,
    publisher: RecordingTaskEventPublisher,
) -> CreateProject:
    """组装创建项目用例，保持测试主体只描述业务路径。"""

    return CreateProject(
        project_repository=projects,
        task_repository=tasks,
        event_publisher=publisher,
    )


def _build_transcribe_video_usecase(
    projects: InMemoryProjectRepository,
    tasks: InMemoryTaskRepository,
    subtitles: InMemorySubtitleRepository,
    media_probe: RecordingMediaProbe,
    audio_extractor: RecordingAudioExtractor,
    asr_engine: RecordingAsrEngine,
    srt_writer: RecordingSrtWriter,
    publisher: RecordingTaskEventPublisher,
) -> TranscribeVideo:
    """按阶段 2 目标装配识别用例。

    当前生产代码还没有这些依赖参数，所以这个工厂会先失败。
    这个失败正是 S2-13 需要留下的红灯：下一步 S2-14 应让
    `TranscribeVideo` 成为探测、抽音频、ASR 和字幕写出的编排入口。
    """

    try:
        return TranscribeVideo(
            project_repository=projects,
            task_repository=tasks,
            subtitle_repository=subtitles,
            media_probe=media_probe,
            audio_extractor=audio_extractor,
            asr_engine=asr_engine,
            srt_writer=srt_writer,
            event_publisher=publisher,
        )
    except TypeError as exc:
        raise AssertionError(
            "`TranscribeVideo` 尚未接收阶段 2 端到端识别链路所需依赖："
            "需要能编排媒体探测、抽音频、ASR 和 `SRT` 写出。"
        ) from exc


@pytest.fixture()
def workspace_temp_dir() -> Path:
    """在仓库内创建测试临时目录，避开受限的系统临时目录。

    当前执行环境对 Windows 用户临时目录可能没有稳定权限。
    把测试产物放在仓库内 `.tmp/` 下，可以让端到端测试仍然只操作工作区。
    """

    temp_dir = Path(".tmp") / "tests" / f"transcribe-flow-{uuid4().hex}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_transcribe_video_flow_creates_project_and_writes_source_srt(
    workspace_temp_dir: Path,
) -> None:
    """应串起创建项目、媒体探测、抽音频、ASR 和原文 `SRT` 产物。"""

    # arrange：先创建项目，这是阶段 2 主链路的入口。
    projects = InMemoryProjectRepository()
    tasks = InMemoryTaskRepository()
    subtitles = InMemorySubtitleRepository()
    publisher = RecordingTaskEventPublisher()
    workspace = WorkspaceManager(workspace_temp_dir / "workspace")
    source_video = _create_demo_source_video(workspace_temp_dir)

    create_project = _build_create_project_usecase(projects, tasks, publisher)
    create_result = create_project.execute(
        CreateProjectInput(
            source_video=source_video,
            source_language="ja-JP",
            target_language="zh-CN",
            workspace_dir=workspace.root,
        )
    )

    project_dir = workspace.ensure_project_structure(create_result.project.project_id)
    create_result.project.workspace_dir = project_dir
    projects.save(create_result.project)

    media_probe = RecordingMediaProbe(calls=[])
    audio_extractor = RecordingAudioExtractor(calls=[])
    asr_engine = RecordingAsrEngine(calls=[])
    srt_writer = RecordingSrtWriter()
    transcribe_video = _build_transcribe_video_usecase(
        projects=projects,
        tasks=tasks,
        subtitles=subtitles,
        media_probe=media_probe,
        audio_extractor=audio_extractor,
        asr_engine=asr_engine,
        srt_writer=srt_writer,
        publisher=publisher,
    )

    # act：未来 S2-14 中，识别用例应只需要项目编号就能从项目记录继续主链路。
    result = transcribe_video.execute(project_id=create_result.project.project_id)

    # assert：先检查调用顺序中的关键路径，确认每一层职责都被串起来。
    expected_audio_path = project_dir / "temp" / "source.wav"
    expected_srt_path = project_dir / "subtitles" / "source.srt"

    assert media_probe.calls == [source_video]
    assert audio_extractor.calls == [(source_video, expected_audio_path)]
    assert asr_engine.calls == [(expected_audio_path, "ja-JP")]
    assert srt_writer.calls
    assert srt_writer.calls[-1][1] == expected_srt_path

    # assert：再检查最终业务结果和正式字幕产物。
    saved_segments = subtitles.get_source_segments(create_result.project.project_id)
    assert result.project_id == create_result.project.project_id
    assert result.source_segments == saved_segments
    assert result.task.status is TaskStatus.SUCCEEDED
    assert result.task.checkpoint is TaskCheckpoint.TRANSCRIBED
    assert result.runtime_message == "实际使用 medium + CUDA + float16 完成识别。"
    assert result.task.message == result.runtime_message
    assert projects.get_by_id(create_result.project.project_id).status is ProjectStatus.PROCESSING
    assert expected_audio_path.exists()
    assert expected_srt_path.exists()
    assert "第一句原文字幕" in expected_srt_path.read_text(encoding="utf-8")


def test_transcribe_video_flow_reuses_audio_and_complete_transcript_cache(
    workspace_temp_dir: Path,
) -> None:
    """缓存音频和完整原文字幕都存在时，不应重复执行高成本步骤。"""

    # arrange：先创建项目和完整缓存状态。
    projects = InMemoryProjectRepository()
    tasks = InMemoryTaskRepository()
    subtitles = InMemorySubtitleRepository()
    publisher = RecordingTaskEventPublisher()
    workspace = WorkspaceManager(workspace_temp_dir / "workspace")
    source_video = _create_demo_source_video(workspace_temp_dir)
    create_result = _build_create_project_usecase(projects, tasks, publisher).execute(
        CreateProjectInput(
            source_video=source_video,
            source_language="ja-JP",
            target_language="zh-CN",
            workspace_dir=workspace.root,
        )
    )
    project_dir = workspace.ensure_project_structure(create_result.project.project_id)
    create_result.project.workspace_dir = project_dir
    projects.save(create_result.project)

    cached_audio_path = project_dir / "temp" / "source.wav"
    cached_audio_path.write_bytes(b"cached wav data")
    cached_srt_path = project_dir / "subtitles" / "source.srt"
    cached_srt_path.write_text("缓存字幕", encoding="utf-8")
    cached_segments = RecordingAsrEngine(calls=[]).transcribe(
        cached_audio_path,
        "ja-JP",
    )
    subtitles.save_source_segments(create_result.project.project_id, cached_segments)

    media_probe = RecordingMediaProbe(calls=[])
    audio_extractor = RecordingAudioExtractor(calls=[])
    asr_engine = RecordingAsrEngine(calls=[])
    srt_writer = RecordingSrtWriter()
    usecase = _build_transcribe_video_usecase(
        projects=projects,
        tasks=tasks,
        subtitles=subtitles,
        media_probe=media_probe,
        audio_extractor=audio_extractor,
        asr_engine=asr_engine,
        srt_writer=srt_writer,
        publisher=publisher,
    )

    # act
    result = usecase.execute(project_id=create_result.project.project_id)

    # assert：仍会探测源媒体确认输入有效，但不会重复抽音频、识别或写字幕。
    assert media_probe.calls == [source_video]
    assert audio_extractor.calls == []
    assert asr_engine.calls == []
    assert srt_writer.calls == []
    assert result.source_segments == cached_segments
    assert result.reused_audio is True
    assert result.reused_transcript is True
    assert result.audio_path == cached_audio_path
    assert result.subtitle_path == cached_srt_path
