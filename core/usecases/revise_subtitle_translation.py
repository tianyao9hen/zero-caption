"""单条字幕译文修订用例。

本模块位于核心层，负责校验选中的字幕、保存用户编辑或调用一次翻译端口，
然后同步结构化字幕和正式 `SRT` 文件。它不依赖 Qt、SQLite 或具体网络客户端。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from uuid import uuid4

from core.domain.entities import Project, Task
from core.domain.enums import TaskCheckpoint
from core.dto.subtitle_dto import (
    EditSubtitleTranslationInput,
    RetranslateSubtitleInput,
    SubtitleSegmentDTO,
    SubtitleTranslationItemDTO,
    SubtitleTranslationUpdateResult,
    TranslationProgressDTO,
)
from core.ports.events import TaskEventPublisher, TranslationProgressPublisher
from core.ports.repository import ProjectRepository, SubtitleRepository, TaskRepository
from core.ports.subtitle import SubtitleWriter
from core.ports.translator import Translator


@dataclass(slots=True)
class ReviseSubtitleTranslation:
    """修订指定字幕的译文，并同步数据库与字幕文件。

    手工编辑不会访问网络；重新翻译只把选中字幕的原文和语言信息交给
    `Translator`。两种操作都会产生独立任务记录，便于用户追踪成功或失败。
    """

    project_repository: ProjectRepository
    task_repository: TaskRepository
    subtitle_repository: SubtitleRepository
    translator: Translator
    subtitle_writer: SubtitleWriter
    event_publisher: TaskEventPublisher | None = None
    translation_event_publisher: TranslationProgressPublisher | None = None

    def save_edit(
        self,
        request: EditSubtitleTranslationInput,
    ) -> SubtitleTranslationUpdateResult:
        """保存用户输入的一条译文，不调用大模型。

        该方法会替换仓储中相同 `segment_id` 的译文，并重写对应语言的
        正式 `SRT` 文件。空白译文和不存在的字幕编号会被拒绝。
        """

        translated_text = request.translated_text.strip()
        if not translated_text:
            raise ValueError("字幕译文不能为空。")

        project, source_segments, translated_segments, current_index = (
            self._load_existing_translation(
                request.project_id,
                request.segment_id,
            )
        )
        task = self._start_task(
            project,
            task_type="edit_subtitle_translation",
            message=f"正在保存第 {current_index} 条字幕编辑",
        )
        try:
            source_segment = source_segments[current_index - 1]
            replacement = SubtitleSegmentDTO(
                segment_id=source_segment.segment_id,
                start_ms=source_segment.start_ms,
                end_ms=source_segment.end_ms,
                text=translated_text,
                language=project.target_language,
            )
            return self._persist_replacement(
                project=project,
                source_segments=source_segments,
                translated_segments=translated_segments,
                current_index=current_index,
                replacement=replacement,
                task=task,
                success_message=f"已保存第 {current_index} 条字幕编辑",
            )
        except Exception as exc:
            self._mark_failed(task, exc)
            raise

    def retranslate(
        self,
        request: RetranslateSubtitleInput,
    ) -> SubtitleTranslationUpdateResult:
        """只调用一次大模型，重新翻译指定的一条字幕。

        原有译文会一直保留到新译文成功返回并通过校验，网络失败不会删除
        用户已有结果。成功后会同步仓储、`SRT` 文件和实时界面事件。
        """

        project, source_segments, translated_segments, current_index = (
            self._load_existing_translation(
                request.project_id,
                request.segment_id,
            )
        )
        task = self._start_task(
            project,
            task_type="retranslate_subtitle",
            message=f"正在重新翻译第 {current_index} 条字幕",
        )
        try:
            # 核心层在这里显式只传一条字幕，保证“重新翻译单句”不会导致
            # 其他已经人工校对过的译文再次被模型覆盖。
            source_segment = source_segments[current_index - 1]
            result = self.translator.translate_segments(
                segments=[source_segment],
                source_language=project.source_language,
                target_language=project.target_language,
                context=(
                    request.context
                    if request.context is not None
                    else project.translation_context or None
                ),
            )
            if len(result) != 1 or not result[0].text.strip():
                raise ValueError("单句重新翻译必须返回且只返回一条非空字幕。")

            replacement = SubtitleSegmentDTO(
                segment_id=source_segment.segment_id,
                start_ms=source_segment.start_ms,
                end_ms=source_segment.end_ms,
                text=result[0].text.strip(),
                language=project.target_language,
            )
            return self._persist_replacement(
                project=project,
                source_segments=source_segments,
                translated_segments=translated_segments,
                current_index=current_index,
                replacement=replacement,
                task=task,
                success_message=f"已重新翻译第 {current_index} 条字幕",
            )
        except Exception as exc:
            self._mark_failed(task, exc)
            raise

    def _load_existing_translation(
        self,
        project_id: str,
        segment_id: str,
    ) -> tuple[Project, list[SubtitleSegmentDTO], list[SubtitleSegmentDTO], int]:
        """读取项目和字幕，并返回目标字幕在原文中的一基序号。"""

        project = self.project_repository.get_by_id(project_id)
        if project is None:
            raise ValueError(f"未找到项目：{project_id}")

        source_segments = self.subtitle_repository.get_source_segments(project_id)
        translated_segments = self.subtitle_repository.get_translated_segments(
            project_id,
            project.target_language,
        )
        source_ids = [segment.segment_id for segment in source_segments]
        translated_ids = {segment.segment_id for segment in translated_segments}
        if segment_id not in source_ids or segment_id not in translated_ids:
            raise ValueError("未找到可修订的字幕翻译结果。")
        return (
            project,
            source_segments,
            translated_segments,
            source_ids.index(segment_id) + 1,
        )

    def _start_task(
        self,
        project: Project,
        task_type: str,
        message: str,
    ) -> Task:
        """创建并持久化一条修订任务，随后发布运行状态。"""

        task = Task(
            task_id=f"task-{uuid4().hex}",
            project_id=project.project_id,
            task_type=task_type,
        )
        task.start(message)
        task.update_progress(
            progress=50,
            current_step=message,
            checkpoint=TaskCheckpoint.TRANSLATED,
            message=message,
        )
        self.task_repository.save(task)
        if self.event_publisher is not None:
            self.event_publisher.publish(task)
        return task

    def _persist_replacement(
        self,
        project: Project,
        source_segments: list[SubtitleSegmentDTO],
        translated_segments: list[SubtitleSegmentDTO],
        current_index: int,
        replacement: SubtitleSegmentDTO,
        task: Task,
        success_message: str,
    ) -> SubtitleTranslationUpdateResult:
        """替换单条译文，按原文顺序保存，并重写正式字幕文件。"""

        # 第一步：只替换指定编号，其他译文对象保持不变。
        # 随后按原文顺序整理，防止历史数据顺序异常影响 `SRT` 时间轴。
        translated_by_id = {
            segment.segment_id: segment for segment in translated_segments
        }
        translated_by_id[replacement.segment_id] = replacement
        ordered_segments = [
            translated_by_id[source.segment_id]
            for source in source_segments
            if source.segment_id in translated_by_id
        ]

        # 第二步：先把完整新字幕写到临时文件，再保存结构化数据，最后用
        # 原子重命名替换正式 `SRT`。磁盘写入失败时旧译文和旧文件都不变。
        subtitle_path = self._subtitle_path(project)
        temporary_path = subtitle_path.with_suffix(".srt.tmp")
        self.subtitle_writer.write_file(ordered_segments, temporary_path)
        database_updated = False
        try:
            self.subtitle_repository.save_translated_segments(
                project.project_id,
                project.target_language,
                ordered_segments,
            )
            database_updated = True
            temporary_path.replace(subtitle_path)
        except Exception:
            # 正式文件替换失败时把仓储恢复为旧列表，保证界面重启后不会
            # 读取到尚未落盘的译文。回滚仍复用仓储自己的事务能力。
            if database_updated:
                self.subtitle_repository.save_translated_segments(
                    project.project_id,
                    project.target_language,
                    translated_segments,
                )
            temporary_path.unlink(missing_ok=True)
            raise

        # 第三步：更新项目时间并完成任务，让任务历史在重启后仍能说明
        # 最近一次操作。这里不改变项目成功/失败状态，避免掩盖之前的导出错误。
        project.touch()
        self.project_repository.save(project)
        task.mark_succeeded(success_message, TaskCheckpoint.TRANSLATED)
        self.task_repository.save(task)
        if self.event_publisher is not None:
            self.event_publisher.publish(task)

        source_segment = source_segments[current_index - 1]
        item = SubtitleTranslationItemDTO(
            project_id=project.project_id,
            segment_id=replacement.segment_id,
            current_index=current_index,
            total_segments=len(source_segments),
            start_ms=replacement.start_ms,
            end_ms=replacement.end_ms,
            source_text=source_segment.text,
            translated_text=replacement.text,
        )
        if self.translation_event_publisher is not None:
            self.translation_event_publisher.publish_translation(
                TranslationProgressDTO(
                    task_id=task.task_id,
                    current_index=current_index,
                    total_segments=len(source_segments),
                    source_text=source_segment.text,
                    translated_text=replacement.text,
                    project_id=project.project_id,
                    segment_id=replacement.segment_id,
                    start_ms=replacement.start_ms,
                    end_ms=replacement.end_ms,
                )
            )
        return SubtitleTranslationUpdateResult(
            project_id=project.project_id,
            task=task,
            item=item,
            subtitle_path=subtitle_path,
        )

    def _mark_failed(self, task: Task, error: Exception) -> None:
        """记录修订失败，但不把整个视频项目改成失败状态。"""

        task.mark_failed(str(error) or error.__class__.__name__)
        self.task_repository.save(task)
        if self.event_publisher is not None:
            self.event_publisher.publish(task)

    @staticmethod
    def _subtitle_path(project: Project) -> Path:
        """生成与完整翻译用例一致的目标语言字幕路径。"""

        safe_name = re.sub(
            r"[^0-9A-Za-z_-]+",
            "_",
            project.target_language,
        ).strip("_")
        return project.workspace_dir / "subtitles" / (
            f"translated-{safe_name or 'translated'}.srt"
        )
