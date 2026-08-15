"""本地视频识别用例模块。

这个文件位于核心层，负责编排“媒体探测 -> 音频抽取 -> 本地识别
-> 字幕后处理 -> `SRT` 写出”。它只依赖端口，不直接调用具体的
`FFmpeg`、`ffprobe` 或 `faster-whisper` 实现。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from core.domain.entities import Task
from core.domain.enums import TaskCheckpoint
from core.dto.subtitle_dto import TranscribeVideoInput, TranscribeVideoResult
from core.ports.asr import AsrEngine, AsrRuntimeReporter
from core.ports.events import TaskEventPublisher
from core.ports.media import AudioExtractor, MediaProbe
from core.ports.repository import ProjectRepository, SubtitleRepository, TaskRepository
from core.ports.subtitle import (
    SubtitleAlignerPort,
    SubtitleFormatterPort,
    SubtitleWriter,
)


@dataclass(slots=True)
class TranscribeVideo:
    """编排本地识别流程并产出项目级原文字幕。"""

    project_repository: ProjectRepository
    task_repository: TaskRepository
    subtitle_repository: SubtitleRepository
    asr_engine: AsrEngine
    event_publisher: TaskEventPublisher | None = None
    media_probe: MediaProbe | None = None
    audio_extractor: AudioExtractor | None = None
    subtitle_formatter: SubtitleFormatterPort | None = None
    subtitle_aligner: SubtitleAlignerPort | None = None
    srt_writer: SubtitleWriter | None = None

    def execute(
        self,
        request: TranscribeVideoInput | None = None,
        *,
        project_id: str | None = None,
    ) -> TranscribeVideoResult:
        """执行识别流程。

        参数：
            request：稳定的识别输入 DTO。调用方已经准备好音频时可传
                `audio_path`，这样用例会跳过媒体探测和抽音频。
            project_id：常规主链路的便捷入口。只传项目编号时，
                用例会从项目记录推导源视频、语言和项目级产物路径。

        返回：
            包含任务快照、字幕片段和本次产物路径的识别结果。

        副作用：
            会更新项目和任务仓储，可能抽取音频并写出 `SRT` 文件。
        """

        request = self._resolve_request(request=request, project_id=project_id)

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
        self.task_repository.save(task)
        self._publish(task)

        media = None
        subtitle_path: Path | None = None
        reused_audio = False
        reused_transcript = False
        runtime_message = ""

        try:
            # 第一步：如果调用方没有准备音频，就先探测源视频并抽取音轨。
            # 音频文件固定落在项目 `temp/` 目录，存在时可以直接复用。
            audio_path = request.audio_path
            if audio_path is None:
                media_probe = self._require_dependency(self.media_probe, "媒体探测器")
                audio_extractor = self._require_dependency(
                    self.audio_extractor,
                    "音频抽取器",
                )
                media = media_probe.probe(project.source_video)
                if not media.audio_streams:
                    raise ValueError("源视频不包含可用于识别的音频流。")

                audio_path = project.workspace_dir / "temp" / "source.wav"
                if audio_path.exists():
                    reused_audio = True
                else:
                    audio_path = audio_extractor.extract_audio(
                        source_path=project.source_video,
                        output_path=audio_path,
                    )

            task.update_progress(
                progress=30,
                current_step="准备识别音频",
                checkpoint=TaskCheckpoint.AUDIO_EXTRACTED,
                message="已复用缓存音频" if reused_audio else "音频已准备好",
            )
            self.task_repository.save(task)
            self._publish(task)

            # 第二步：优先复用已经保存的原文字幕。
            # 只有仓储片段和正式 `SRT` 文件同时存在时才算完整缓存命中，
            # 避免数据库状态与磁盘产物不一致时错误跳过识别。
            if self.srt_writer is not None:
                subtitle_path = project.workspace_dir / "subtitles" / "source.srt"
            cached_segments = self.subtitle_repository.get_source_segments(project.project_id)
            can_reuse_transcript = bool(cached_segments) and (
                subtitle_path is None or subtitle_path.exists()
            )

            if can_reuse_transcript:
                segments = cached_segments
                reused_transcript = True
                runtime_message = "已复用原文字幕，未重新加载识别模型。"
            else:
                language = request.language or project.source_language
                segments = self.asr_engine.transcribe(
                    audio_path=audio_path,
                    language=None if language == "auto" else language,
                )
                if isinstance(self.asr_engine, AsrRuntimeReporter):
                    runtime_message = self.asr_engine.runtime_summary()

                # 第三步：依次做保守去重和时间轴规整。
                # 两个步骤职责不同，顺序不能交换：先删重复片段，
                # 再根据剩余片段确定最终不重叠时间轴。
                if self.subtitle_formatter is not None:
                    segments = self.subtitle_formatter.remove_duplicates(segments)
                if self.subtitle_aligner is not None:
                    segments = self.subtitle_aligner.normalize_timeline(segments)

                self.subtitle_repository.save_source_segments(project.project_id, segments)
                if self.srt_writer is not None and subtitle_path is not None:
                    subtitle_path = self.srt_writer.write_file(segments, subtitle_path)

            # 第四步：所有结构化数据和正式字幕都成功保存后，再推进检查点。
            task.mark_succeeded(
                runtime_message
                or ("已复用原文字幕" if reused_transcript else "识别完成"),
                checkpoint=TaskCheckpoint.TRANSCRIBED,
            )
            self.task_repository.save(task)
            self._publish(task)

            return TranscribeVideoResult(
                project_id=project.project_id,
                task=task,
                source_segments=segments,
                audio_path=audio_path,
                subtitle_path=subtitle_path,
                media=media,
                reused_audio=reused_audio,
                reused_transcript=reused_transcript,
                runtime_message=runtime_message,
            )
        except Exception as exc:
            # 失败状态先写仓储再发布，保证未来 UI 订阅到的状态
            # 不会领先于真实持久化状态。
            error_message = str(exc) or exc.__class__.__name__
            task.mark_failed(error_message)
            project.mark_failed(error_message)
            self.task_repository.save(task)
            self.project_repository.save(project)
            self._publish(task)
            raise

    def _resolve_request(
        self,
        request: TranscribeVideoInput | None,
        project_id: str | None,
    ) -> TranscribeVideoInput:
        """把 DTO 调用和仅项目编号调用统一成一个输入对象。"""

        if request is not None and project_id is not None:
            raise ValueError("识别请求和项目编号不能同时传入。")
        if request is not None:
            return request
        if project_id:
            return TranscribeVideoInput(project_id=project_id)
        raise ValueError("识别流程必须提供请求对象或项目编号。")

    def _require_dependency(self, dependency, name: str):
        """确保常规主链路已经装配必要基础设施端口。"""

        if dependency is None:
            raise RuntimeError(f"识别流程尚未装配{name}。")
        return dependency

    def _publish(self, task: Task) -> None:
        """在配置了事件发布器时发布最新任务快照。"""

        if self.event_publisher is not None:
            self.event_publisher.publish(task)
