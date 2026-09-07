"""本地视频识别用例模块。

这个文件位于核心层，负责编排“媒体探测 -> 音频抽取 -> 本地识别
-> 字幕后处理 -> `SRT` 写出”。它只依赖端口，不直接调用具体的
`FFmpeg`、`ffprobe` 或 `faster-whisper` 实现。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from core.domain.entities import Task
from core.domain.enums import TaskCheckpoint
from core.dto.subtitle_dto import (
    SubtitleSegmentDTO,
    TranscribeVideoInput,
    TranscribeVideoResult,
)
from core.ports.asr import AsrCacheKeyProvider, AsrEngine, AsrRuntimeReporter
from core.ports.events import TaskEventPublisher
from core.ports.media import (
    AudioExtractor,
    AudioSegmentExtractor,
    AudioSegmentPlanner,
    MediaProbe,
)
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
    audio_segment_extractor: AudioSegmentExtractor | None = None
    audio_segment_planner: AudioSegmentPlanner | None = None
    subtitle_formatter: SubtitleFormatterPort | None = None
    subtitle_aligner: SubtitleAlignerPort | None = None
    srt_writer: SubtitleWriter | None = None
    max_subtitle_duration_ms: int = 30_000

    def execute(
        self,
        request: TranscribeVideoInput | None = None,
        *,
        project_id: str | None = None,
    ) -> TranscribeVideoResult:
        """执行识别流程。

        参数：
            request：稳定的识别输入 DTO。调用方已经准备好音频时可传
                `audio_path`，这样用例会跳过媒体探测和抽音频；传入
                `output_path` 时还会把原文字幕写到用户选择的位置。
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
        chunk_count = 1

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
            # 并且识别参数签名必须一致。旧版本没有签名时会主动重新识别，
            # 避免继续复用已经确认存在 VAD 时间轴问题的历史结果。
            if self.srt_writer is not None:
                subtitle_path = project.workspace_dir / "subtitles" / "source.srt"
            cache_signature = self._transcription_cache_signature()
            cache_signature_path = (
                project.workspace_dir / "cache" / "transcription-signature.txt"
            )
            cached_segments = self.subtitle_repository.get_source_segments(project.project_id)
            can_reuse_transcript = bool(cached_segments) and (
                subtitle_path is None or subtitle_path.exists()
            ) and self._cache_signature_matches(
                cache_signature_path,
                cache_signature,
            )

            if can_reuse_transcript:
                segments = cached_segments
                reused_transcript = True
                runtime_message = "已复用原文字幕，未重新加载识别模型。"
            else:
                language = request.language or project.source_language
                segments, chunk_count = self._transcribe_audio(
                    audio_path=audio_path,
                    duration_ms=media.duration_ms if media is not None else 0,
                    language=None if language == "auto" else language,
                    project_temp_dir=project.workspace_dir / "temp",
                    task=task,
                    cache_signature=cache_signature,
                )
                if isinstance(self.asr_engine, AsrRuntimeReporter):
                    runtime_message = self.asr_engine.runtime_summary()
                if chunk_count > 1:
                    runtime_message = (
                        f"{runtime_message}；已分 {chunk_count} 个音频块处理"
                        if runtime_message
                        else f"已分 {chunk_count} 个音频块处理"
                    )

                # 第三步：依次做保守去重和时间轴规整。
                # 两个步骤职责不同，顺序不能交换：先删重复片段，
                # 再根据剩余片段确定最终不重叠时间轴。
                if self.subtitle_formatter is not None:
                    segments = self.subtitle_formatter.remove_duplicates(segments)
                if self.subtitle_aligner is not None:
                    segments = self.subtitle_aligner.normalize_timeline(segments)
                segments = self._reindex_segments(segments, cache_signature)
                self._validate_segments(
                    segments=segments,
                    duration_ms=media.duration_ms if media is not None else 0,
                )

                self.subtitle_repository.save_source_segments(project.project_id, segments)
                if self.srt_writer is not None and subtitle_path is not None:
                    subtitle_path = self.srt_writer.write_file(segments, subtitle_path)
                self._write_cache_signature(cache_signature_path, cache_signature)

            # 第四步：项目字幕用于缓存和恢复，用户选择的路径则是可直接
            # 找到的成果副本。复用识别缓存时也重新写出成果，保证用户删除
            # 旧副本后点击续跑仍能恢复到原保存位置。
            result_subtitle_path = subtitle_path
            if request.output_path is not None:
                if request.output_path.suffix.lower() != ".srt":
                    raise ValueError("原文字幕的保存路径必须使用 .srt 扩展名。")
                writer = self._require_dependency(self.srt_writer, "字幕写出器")
                result_subtitle_path = writer.write_file(
                    segments,
                    request.output_path,
                )

            # 第五步：所有结构化数据、项目字幕和用户成果都成功保存后，
            # 再推进检查点，避免界面先显示完成而目标文件还没有落盘。
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
                subtitle_path=result_subtitle_path,
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

    def _transcribe_audio(
        self,
        audio_path: Path,
        duration_ms: int,
        language: str | None,
        project_temp_dir: Path,
        task: Task,
        cache_signature: str | None,
    ) -> tuple[list[SubtitleSegmentDTO], int]:
        """识别单个音频或按固定窗口识别长音频。

        长音频块会先落盘，再逐块交给 ASR 端口。这样模型每次只解码一个
        有限大小的文件，不需要把两小时音频长期驻留内存。返回的时间戳会
        加回每块在原始音频中的绝对偏移。
        """

        planner = self.audio_segment_planner
        extractor = self.audio_segment_extractor
        if planner is None or extractor is None or duration_ms <= 0:
            return self.asr_engine.transcribe(audio_path, language=language), 1

        ranges = planner.plan_segments(duration_ms)
        if len(ranges) <= 1:
            return self.asr_engine.transcribe(audio_path, language=language), 1

        signature_dir = (cache_signature or "legacy")[:16]
        chunk_dir = project_temp_dir / "asr-chunks" / signature_dir
        recognized: list[SubtitleSegmentDTO] = []
        active_language = language

        # 第一步：逐块生成稳定文件名。已经完整存在的块可以在任务恢复时复用。
        # 第二步：识别局部时间轴，并加回当前块的绝对开始偏移。
        # 第三步：每块完成后持久化任务进度，让桌面界面明确显示当前文件块。
        for index, segment_range in enumerate(ranges, start=1):
            chunk_path = chunk_dir / (
                f"chunk-{segment_range.start_ms:010d}-{segment_range.end_ms:010d}.wav"
            )
            if not chunk_path.is_file() or chunk_path.stat().st_size == 0:
                extractor.extract_audio_segment(
                    source_path=audio_path,
                    output_path=chunk_path,
                    start_ms=segment_range.start_ms,
                    end_ms=segment_range.end_ms,
                )

            local_segments = self.asr_engine.transcribe(
                chunk_path,
                language=active_language,
            )
            if active_language is None and local_segments:
                detected = local_segments[0].language
                active_language = None if detected == "unknown" else detected

            for local_segment in local_segments:
                recognized.append(
                    replace(
                        local_segment,
                        segment_id=f"chunk-{index}-{local_segment.segment_id}",
                        start_ms=local_segment.start_ms + segment_range.start_ms,
                        end_ms=local_segment.end_ms + segment_range.start_ms,
                    )
                )

            progress = 30 + round(index / len(ranges) * 25)
            task.update_progress(
                progress=progress,
                current_step=f"分块识别 {index}/{len(ranges)}",
                checkpoint=TaskCheckpoint.AUDIO_EXTRACTED,
                message=f"已完成第 {index} 个音频块",
            )
            self.task_repository.save(task)
            self._publish(task)

        return recognized, len(ranges)

    def _transcription_cache_signature(self) -> str | None:
        """组合 ASR 参数和分块规则，生成项目级识别缓存签名。"""

        if not isinstance(self.asr_engine, AsrCacheKeyProvider):
            return None
        planner = self.audio_segment_planner
        payload = "|".join(
            [
                "zero-caption-transcription-v3",
                self.asr_engine.cache_key(),
                str(getattr(planner, "chunk_duration_ms", 0)),
                str(getattr(planner, "overlap_ms", 0)),
                str(self.max_subtitle_duration_ms),
            ]
        )
        return sha256(payload.encode("utf-8")).hexdigest()

    def _cache_signature_matches(
        self,
        path: Path,
        expected: str | None,
    ) -> bool:
        """判断结构化字幕是否来自当前识别参数。"""

        if expected is None:
            return True
        if not path.is_file():
            return False
        try:
            return path.read_text(encoding="utf-8").strip() == expected
        except OSError:
            return False

    def _write_cache_signature(self, path: Path, signature: str | None) -> None:
        """在字幕和数据库都保存成功后写入识别缓存签名。"""

        if signature is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{signature}\n", encoding="utf-8")

    def _reindex_segments(
        self,
        segments: list[SubtitleSegmentDTO],
        cache_signature: str | None,
    ) -> list[SubtitleSegmentDTO]:
        """为新识别结果生成稳定且不会命中旧译文缓存的片段编号。"""

        if cache_signature is None:
            return segments
        prefix = cache_signature[:12]
        return [
            replace(segment, segment_id=f"{prefix}-{index}")
            for index, segment in enumerate(segments, start=1)
        ]

    def _validate_segments(
        self,
        segments: list[SubtitleSegmentDTO],
        duration_ms: int,
    ) -> None:
        """拒绝写出明显损坏的字幕时间轴。

        这里不把异常字幕强制截短，因为那会掩盖漏识别。出现超过模型单窗口
        范围的字幕时直接失败，用户重试后才能得到可信结果。
        """

        if not segments:
            raise ValueError("没有识别到可写出的语音字幕。")
        for index, segment in enumerate(segments, start=1):
            duration = segment.end_ms - segment.start_ms
            if segment.start_ms < 0 or duration <= 0:
                raise ValueError(f"第 {index} 条字幕时间范围无效。")
            if duration > self.max_subtitle_duration_ms:
                raise ValueError(
                    f"第 {index} 条字幕持续 {duration / 1000:.2f} 秒，"
                    "超过识别质量上限，请重新识别。"
                )
            if duration_ms > 0 and segment.end_ms > duration_ms + 2_000:
                raise ValueError(f"第 {index} 条字幕超出源音频时长。")

    def _require_dependency(self, dependency, name: str):
        """确保常规主链路已经装配必要基础设施端口。"""

        if dependency is None:
            raise RuntimeError(f"识别流程尚未装配{name}。")
        return dependency

    def _publish(self, task: Task) -> None:
        """在配置了事件发布器时发布最新任务快照。"""

        if self.event_publisher is not None:
            self.event_publisher.publish(task)
