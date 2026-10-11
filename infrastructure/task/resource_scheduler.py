"""进程内高资源任务调度器。

这个模块属于基础设施层，使用标准库条件变量限制高资源操作的并发数。
它不判断业务步骤是否昂贵；哪些操作需要受限由核心服务明确决定。
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Condition, Lock
from typing import TypeVar


ResultT = TypeVar("ResultT")


@dataclass(slots=True)
class _ResourceGroup:
    """描述一类高资源操作当前占用的槽位和等待队列。

    `queue` 保存按到达顺序发放的编号。先进先出的等待队列让多个视频任务
    按用户创建顺序依次进入识别或导出，而不是由操作系统随机唤醒某个线程。
    """

    limit: int = 1
    active_count: int = 0
    next_ticket: int = 0
    queue: deque[int] = field(default_factory=deque)


@dataclass(slots=True)
class SerialResourceScheduler:
    """让多个后台任务按操作类别共享有限数量的高资源执行槽位。

    同一个 `TaskService` 会用不同名称申请资源：`transcribe_video` 代表本地
    识别，`export_video` 代表视频导出。两类操作各自拥有独立槽位，因此长时间
    的识别任务不会把用户的“下载成品”请求一起挡住。

    同类操作内部按先进先出排队。这样用户先创建的视频会先开始识别，
    界面上的任务顺序与实际执行顺序保持一致。

    `max_concurrency` 仍然是默认槽位数量；`limits` 可以为单个操作类别
    单独覆盖，例如给导出预留一个独立槽位。
    """

    max_concurrency: int = 1
    limits: dict[str, int] = field(default_factory=dict)
    _groups: dict[str, _ResourceGroup] = field(default_factory=dict, init=False, repr=False)
    _condition: Condition = field(default_factory=Condition, init=False, repr=False)

    def __post_init__(self) -> None:
        """校验并初始化默认并发边界，不访问文件或外部系统。"""

        if self.max_concurrency <= 0:
            raise ValueError("高资源任务并发数必须大于 0。")
        for name, limit in self.limits.items():
            if limit <= 0:
                raise ValueError(f"高资源任务并发数必须大于 0：{name}。")
        # 显式创建一次锁对象。`dataclass(slots=True)` 不允许在字段默认值里
        # 直接写 `Condition()`，否则所有实例会共享同一把锁。
        self._condition = Condition(Lock())

    def set_limit(self, operation_name: str, limit: int) -> None:
        """调整某类操作的并发上限，并立即唤醒可能已经满足条件的等待者。

        参数：
            operation_name：与 `run()` 使用的同名稳定操作类别。
            limit：新的并发上限，必须大于零。

        副作用：
            已经进入执行的操作不受影响；新上限只对后续排队者生效。
        """

        if limit <= 0:
            raise ValueError("高资源任务并发数必须大于 0。")
        with self._condition:
            self.limits[operation_name] = limit
            group = self._groups.get(operation_name)
            if group is not None:
                group.limit = limit
            self._condition.notify_all()

    def limit_of(self, operation_name: str) -> int:
        """返回某类操作当前生效的并发上限，供界面展示和测试读取。"""

        group = self._groups.get(operation_name)
        if group is not None:
            return group.limit
        return self.limits.get(operation_name, self.max_concurrency)

    def run(
        self,
        operation_name: str,
        operation: Callable[[], ResultT],
    ) -> ResultT:
        """等待一个资源槽位并执行操作，结束后一定归还槽位。

        参数：
            operation_name：用于分组和诊断的稳定操作类别名称。
            operation：需要受并发保护的同步函数。

        返回：
            原函数返回值。

        副作用：
            可能阻塞当前后台线程等待槽位，但不会阻塞 Qt 界面线程。
            同类操作按调用到达顺序获得槽位。
        """

        self._acquire(operation_name)
        try:
            return operation()
        finally:
            self._release(operation_name)

    def _acquire(self, operation_name: str) -> None:
        """按先进先出顺序占用一个槽位，直到轮到自己且有空闲槽位。"""

        with self._condition:
            group = self._group(operation_name)
            # 第一步：领取排队编号。编号在锁内发放，保证与到达顺序一致。
            ticket = group.next_ticket
            group.next_ticket += 1
            group.queue.append(ticket)

            # 第二步：等待“排在最前”且“有空闲槽位”两个条件同时成立。
            # 用 `while` 而不是 `if`，因为被唤醒时可能只是队列发生了变化。
            while group.queue[0] != ticket or group.active_count >= group.limit:
                self._condition.wait()

            # 第三步：真正占用槽位后离开等待队列，让下一个编号继续判断。
            group.queue.popleft()
            group.active_count += 1
            # 关键：占用槽位会改变队首，下一个等待者的“排在最前”条件
            # 可能因此成立。必须主动唤醒它，否则它会一直睡到下一次释放，
            # 表现为并发上限调大后新任务迟迟不开始。
            self._condition.notify_all()

    def _release(self, operation_name: str) -> None:
        """归还一个槽位并唤醒所有等待者，由它们重新判断是否可进入。"""

        with self._condition:
            group = self._group(operation_name)
            group.active_count = max(0, group.active_count - 1)
            self._condition.notify_all()

    def _group(self, operation_name: str) -> _ResourceGroup:
        """返回某类操作的共享状态，首次访问时按配置创建。"""

        group = self._groups.get(operation_name)
        if group is None:
            group = _ResourceGroup(
                limit=self.limits.get(operation_name, self.max_concurrency),
            )
            self._groups[operation_name] = group
        return group
