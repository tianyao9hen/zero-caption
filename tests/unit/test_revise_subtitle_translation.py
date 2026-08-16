"""单条字幕译文修订用例测试。

测试使用内存仓储和真实 `SRT` 写出器，保护手工编辑、单句重译、失败保留
旧译文这三项行为，不依赖网络、Qt 或真实大模型。
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from core.domain.entities import Project, Task
from core.domain.enums import ProjectStatus, TaskStatus
from core.dto.subtitle_dto import (
    EditSubtitleTranslationInput,
    RetranslateSubtitleInput,
    SubtitleSegmentDTO,
    TranslationProgressDTO,
)
from core.usecases.revise_subtitle_translation import ReviseSubtitleTranslation
from infrastructure.storage.memory_repositories import (
    InMemoryProjectRepository,
    InMemorySubtitleRepository,
    InMemoryTaskRepository,
)
from infrastructure.subtitle.srt_writer import SrtWriter


class RecordingTranslator:
    """记录单句翻译参数，并返回固定的新译文。"""

    def __init__(self, translated_text: str = "重新翻译后的世界") -> None:
        self.translated_text = translated_text
        self.calls: list[
            tuple[list[SubtitleSegmentDTO], str, str, str | None]
        ] = []

    def translate_segments(
        self,
        segments: list[SubtitleSegmentDTO],
        source_language: str,
        target_language: str,
        context: str | None = None,
    ) -> list[SubtitleSegmentDTO]:
        """保存收到的文本参数，并模拟模型返回一条译文。"""

        self.calls.append(
            (list(segments), source_language, target_language, context)
        )
        return [
            replace(
                segments[0],
                text=self.translated_text,
                language=target_language,
            )
        ]


class FailingTranslator(RecordingTranslator):
    """模拟远程模型失败，用于验证旧译文不会被提前清除。"""

    def translate_segments(
        self,
        segments: list[SubtitleSegmentDTO],
        source_language: str,
        target_language: str,
        context: str | None = None,
    ) -> list[SubtitleSegmentDTO]:
        """每次调用都抛出可识别错误。"""

        raise RuntimeError("模拟单句重译失败")


class RecordingPublisher:
    """记录任务状态和字幕更新事件，验证用例会通知界面。"""

    def __init__(self) -> None:
        self.tasks: list[Task] = []
        self.translations: list[TranslationProgressDTO] = []

    def publish(self, task: Task) -> None:
        """保存任务快照。"""

        self.tasks.append(task)

    def publish_translation(self, progress: TranslationProgressDTO) -> None:
        """保存单条字幕更新事件。"""

        self.translations.append(progress)


def _build_usecase(
    tmp_path: Path,
    translator: RecordingTranslator,
) -> tuple[
    ReviseSubtitleTranslation,
    Project,
    InMemorySubtitleRepository,
    InMemoryTaskRepository,
    RecordingPublisher,
]:
    """组装包含两条完整译文的最小修订场景。"""

    projects = InMemoryProjectRepository()
    tasks = InMemoryTaskRepository()
    subtitles = InMemorySubtitleRepository()
    publisher = RecordingPublisher()
    project = Project(
        project_id="project-revision",
        source_video=tmp_path / "lesson.mp4",
        source_language="en",
        target_language="zh-CN",
        workspace_dir=tmp_path / "project-revision",
    )
    project.mark_completed()
    projects.save(project)
    source_segments = [
        SubtitleSegmentDTO("segment-1", 0, 1_000, "hello", "en"),
        SubtitleSegmentDTO("segment-2", 1_000, 2_000, "world", "en"),
    ]
    translated_segments = [
        SubtitleSegmentDTO("segment-1", 0, 1_000, "你好", "zh-CN"),
        SubtitleSegmentDTO("segment-2", 1_000, 2_000, "世界", "zh-CN"),
    ]
    subtitles.save_source_segments(project.project_id, source_segments)
    subtitles.save_translated_segments(
        project.project_id,
        project.target_language,
        translated_segments,
    )
    usecase = ReviseSubtitleTranslation(
        project_repository=projects,
        task_repository=tasks,
        subtitle_repository=subtitles,
        translator=translator,
        subtitle_writer=SrtWriter(),
        event_publisher=publisher,
        translation_event_publisher=publisher,
    )
    return usecase, project, subtitles, tasks, publisher


def test_manual_edit_updates_only_selected_translation_and_srt(tmp_path) -> None:
    """手工编辑应保留其他字幕、不访问模型，并同步正式字幕文件。"""

    # arrange：第二条已有译文将被用户手工校对，第一条用于验证不会误改。
    translator = RecordingTranslator()
    usecase, project, subtitles, _tasks, publisher = _build_usecase(
        tmp_path,
        translator,
    )

    # act：只提交第二条的新文本。
    result = usecase.save_edit(
        EditSubtitleTranslationInput(
            project_id=project.project_id,
            segment_id="segment-2",
            translated_text="  世界，你好  ",
        )
    )

    # assert：数据库、文件和事件使用同一份新译文，模型没有被调用。
    saved = subtitles.get_translated_segments(
        project.project_id,
        project.target_language,
    )
    assert [segment.text for segment in saved] == ["你好", "世界，你好"]
    assert translator.calls == []
    assert result.task.status is TaskStatus.SUCCEEDED
    assert result.item.segment_id == "segment-2"
    assert result.subtitle_path.read_text(encoding="utf-8").count("世界，你好") == 1
    assert publisher.translations[-1].segment_id == "segment-2"
    assert project.status is ProjectStatus.COMPLETED


def test_retranslate_calls_model_once_for_selected_source_and_keeps_other_line(
    tmp_path,
) -> None:
    """单句重译必须只发送选中原文，并保留其他已经校对的译文。"""

    translator = RecordingTranslator("新的世界")
    usecase, project, subtitles, _tasks, _publisher = _build_usecase(
        tmp_path,
        translator,
    )

    result = usecase.retranslate(
        RetranslateSubtitleInput(
            project_id=project.project_id,
            segment_id="segment-2",
            context="保持课程术语",
        )
    )

    assert len(translator.calls) == 1
    assert [segment.segment_id for segment in translator.calls[0][0]] == [
        "segment-2"
    ]
    assert translator.calls[0][1:] == ("en", "zh-CN", "保持课程术语")
    saved = subtitles.get_translated_segments(
        project.project_id,
        project.target_language,
    )
    assert [segment.text for segment in saved] == ["你好", "新的世界"]
    assert result.item.translated_text == "新的世界"


def test_retranslate_reuses_context_saved_with_project(tmp_path) -> None:
    """单句重译未另传上下文时，应复用最初视频任务保存的上下文。"""

    translator = RecordingTranslator("带术语的译文")
    usecase, project, _subtitles, _tasks, _publisher = _build_usecase(
        tmp_path,
        translator,
    )
    project.translation_context = "课程术语：agent 译为智能体"

    usecase.retranslate(
        RetranslateSubtitleInput(
            project_id=project.project_id,
            segment_id="segment-2",
        )
    )

    assert translator.calls[0][3] == "课程术语：agent 译为智能体"


def test_retranslate_failure_preserves_old_translation_and_records_failed_task(
    tmp_path,
) -> None:
    """模型失败时应保留旧译文，只把本次单句任务记录为失败。"""

    usecase, project, subtitles, tasks, _publisher = _build_usecase(
        tmp_path,
        FailingTranslator(),
    )

    with pytest.raises(RuntimeError, match="模拟单句重译失败"):
        usecase.retranslate(
            RetranslateSubtitleInput(
                project_id=project.project_id,
                segment_id="segment-2",
            )
        )

    saved = subtitles.get_translated_segments(
        project.project_id,
        project.target_language,
    )
    assert [segment.text for segment in saved] == ["你好", "世界"]
    assert tasks.list_by_project(project.project_id)[0].status is TaskStatus.FAILED
    assert project.status is ProjectStatus.COMPLETED


def test_manual_edit_file_failure_keeps_old_persisted_translation(tmp_path) -> None:
    """字幕文件无法写入时，不应只更新数据库造成两份结果不一致。"""

    class FailingWriter:
        """模拟磁盘写出失败的字幕端口。"""

        def write_file(self, segments, output_path):
            """拒绝写入并返回明确的磁盘错误。"""

            raise OSError("模拟字幕文件写入失败")

    usecase, project, subtitles, _tasks, _publisher = _build_usecase(
        tmp_path,
        RecordingTranslator(),
    )
    usecase.subtitle_writer = FailingWriter()

    with pytest.raises(OSError, match="模拟字幕文件写入失败"):
        usecase.save_edit(
            EditSubtitleTranslationInput(
                project_id=project.project_id,
                segment_id="segment-2",
                translated_text="不应保存的新译文",
            )
        )

    saved = subtitles.get_translated_segments(
        project.project_id,
        project.target_language,
    )
    assert [segment.text for segment in saved] == ["你好", "世界"]
