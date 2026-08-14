"""进度总线的单元测试，保护后台线程与 UI 线程之间的边界。"""

from core.domain.entities import Task
from core.domain.enums import TaskCheckpoint
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
    assert events[1].progress == 20
    assert bus.drain() == []
