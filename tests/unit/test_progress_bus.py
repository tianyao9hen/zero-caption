"""进度总线的单元测试，保护后台线程与 UI 线程之间的边界。"""

from core.domain.entities import Task
from core.domain.enums import TaskCheckpoint
from core.dto.subtitle_dto import TranslationProgressDTO
from infrastructure.task.progress_bus import ProgressBus


def test_progress_bus_drain_returns_events_without_blocking() -> None:
    """发布的任务快照应按顺序取出，队列为空时立即返回空列表。"""

    # arrange：构造两个不同进度的任务快照。
    bus = ProgressBus()
    first = Task(task_id="task-1", project_id="project-1", task_type="demo")
    first.update_progress(10, "准备", TaskCheckpoint.IMPORTED, "已导入")
    second = Task(task_id="task-2", project_id="project-1", task_type="demo")
    second.update_progress(20, "识别", TaskCheckpoint.AUDIO_EXTRACTED, "已抽取")

    # act：先发布，再一次性消费当前积累的事件。
    bus.publish(first)
    bus.publish(second)
    events = bus.drain()

    # assert：事件内容和顺序保持不变，第二次消费不会等待生产者。
    assert [event.task_id for event in events] == ["task-1", "task-2"]
    assert [event.project_id for event in events] == ["project-1", "project-1"]
    assert events[1].progress == 20
    assert bus.drain() == []


def test_progress_bus_keeps_translation_event_in_publish_order() -> None:
    """逐句译文事件应和普通任务事件共享同一条有序线程安全队列。"""

    bus = ProgressBus()
    progress = TranslationProgressDTO(
        task_id="task-translate",
        current_index=1,
        total_segments=2,
        source_text="hello",
        translated_text="你好",
    )

    bus.publish_translation(progress)

    assert bus.drain() == [progress]


def test_progress_bus_does_not_publish_transcription_success_as_total_100() -> None:
    """完整流程的识别任务成功只代表到达 40%，不能冒充视频处理完成。"""

    bus = ProgressBus()
    task = Task("task-transcribed", "project-1", "transcribe_video")
    task.mark_succeeded("识别完成", TaskCheckpoint.TRANSCRIBED)

    bus.publish(task)

    summary = bus.drain()[0]
    assert summary.progress == 40
