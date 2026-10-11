"""高资源任务调度器测试。

这些测试保护多视频并发时最重要的资源边界：普通流程可以由多个后台线程
同时推进，但识别和视频导出等高资源操作不能同时占满电脑。
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Condition, Event, Lock, Thread, get_ident
from time import monotonic, sleep

import pytest

from infrastructure.task.resource_scheduler import SerialResourceScheduler


def test_resource_scheduler_serializes_heavy_operations() -> None:
    """多个线程进入高资源阶段时，默认应始终只有一个操作真正执行。"""

    # arrange：计数器记录测试期间同时进入高资源操作的最大线程数。
    scheduler = SerialResourceScheduler(max_concurrency=1)
    counter_lock = Lock()
    active_count = 0
    maximum_active_count = 0

    def heavy_operation(operation_index: int) -> int:
        """模拟一个短暂占用 CPU 或显卡的高资源操作。"""

        nonlocal active_count, maximum_active_count
        with counter_lock:
            active_count += 1
            maximum_active_count = max(maximum_active_count, active_count)
        sleep(0.03)
        with counter_lock:
            active_count -= 1
        return operation_index

    # act：四个普通后台线程同时提交高资源操作。
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(
                scheduler.run,
                "transcribe_video",
                lambda index=index: heavy_operation(index),
            )
            for index in range(4)
        ]
        results = [future.result() for future in futures]

    # assert：所有操作都完成，但高资源区从未出现两个并行执行者。
    assert results == [0, 1, 2, 3]
    assert maximum_active_count == 1


def test_resource_scheduler_rejects_nonpositive_concurrency() -> None:
    """高资源并发数必须大于零，避免所有任务永久等待。"""

    with pytest.raises(ValueError, match="高资源任务并发数必须大于 0"):
        SerialResourceScheduler(max_concurrency=0)


def test_resource_scheduler_keeps_operation_names_independent() -> None:
    """识别和导出属于不同类别，长时间识别不应挡住成品导出。"""

    # arrange：识别占满唯一槽位，导出请求在另一个线程里同时到达。
    scheduler = SerialResourceScheduler(max_concurrency=1)
    recognition_started = Event()
    recognition_release = Event()
    export_finished = Event()

    def long_running_recognition() -> None:
        recognition_started.set()
        recognition_release.wait(timeout=5)

    def quick_export() -> None:
        export_finished.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        recognition = executor.submit(
            scheduler.run,
            "transcribe_video",
            long_running_recognition,
        )
        assert recognition_started.wait(timeout=5)

        # act：识别仍在运行时提交导出任务。
        export = executor.submit(scheduler.run, "export_video", quick_export)

        # assert：导出立刻完成，没有被识别阻塞。
        assert export_finished.wait(timeout=2) is True
        recognition_release.set()
        recognition.result(timeout=5)


def test_resource_scheduler_serves_same_name_operations_in_arrival_order() -> None:
    """同一类别的操作应按进入顺序获得槽位，与任务创建顺序一致。"""

    scheduler = SerialResourceScheduler(max_concurrency=1)
    order_lock = Lock()
    order: list[int] = []
    first_started = Event()
    release_first = Event()

    def operation(index: int) -> None:
        if index == 0:
            first_started.set()
            release_first.wait(timeout=5)
        with order_lock:
            order.append(index)

    with ThreadPoolExecutor(max_workers=4) as executor:
        first = executor.submit(scheduler.run, "transcribe_video", lambda: operation(0))
        assert first_started.wait(timeout=5)
        # 后续三个任务按提交顺序排队，槽位释放后必须依次进入。
        pending = [
            executor.submit(scheduler.run, "transcribe_video", lambda i=i: operation(i))
            for i in (1, 2, 3)
        ]
        # 给等待线程足够时间领取排队编号，避免先后顺序与提交顺序颠倒。
        sleep(0.05)
        release_first.set()
        first.result(timeout=5)
        for future in pending:
            future.result(timeout=5)

    assert order == [0, 1, 2, 3]


class _OrderedLock:
    """可以指定“下一个拿到锁的线程”的锁，用来固定并发测试里的先后顺序。

    为什么需要它：`Condition.notify_all()` 会唤醒全部等待者，但这些线程
    回到锁上时谁先谁后由操作系统决定。测试如果依赖这个顺序，就会出现
    偶尔通过、偶尔失败的“竞态测试”。这里在真实互斥锁外面加一层让路规则：
    被指定的线程下一次申请锁时优先通过，其他线程主动等待它先拿到锁。

    这样测试就可以稳定复现“编号靠后的等待者先重新检查条件”这种时序，
    从而确定性地验证调度器是否会正确唤醒新的队首。
    """

    def __init__(self) -> None:
        # `_lock` 才是真正起互斥作用的锁，`_OrderedLock` 只是加了一层让路判断。
        self._lock = Lock()
        # `_owner` 记录当前持有者，供 `Condition._is_owned()` 使用。
        self._owner: int | None = None
        # `_next` 是被指定优先的线程标识，`None` 表示不指定。
        self._next: int | None = None
        # `_granted` 用于通知“被指定线程已经取走锁，其他人不用再让路”。
        self._granted = Event()
        self._granted.set()
        # `_prefer_deadline` 是让路机制的兜底截止时间，避免指定线程异常时卡死。
        self._prefer_deadline: float | None = None

    def prefer_next(self, thread_id: int) -> None:
        """把下一次获取锁的机会指定给 `thread_id`。"""

        self._next = thread_id
        self._granted.clear()
        self._prefer_deadline = monotonic() + 3.0

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        """按让路规则获取底层锁。"""

        thread_id = get_ident()
        while True:
            # 第一步：如果有被指定的线程且不是自己，先把机会让给它。
            if self._next is not None and self._next != thread_id:
                if self._granted.wait(timeout=0.01):
                    continue
                if self._prefer_deadline is not None and monotonic() >= self._prefer_deadline:
                    # 兜底：被指定的线程如果没来申请锁，就撤销让路规则。
                    self._next = None
                    self._granted.set()
                continue

            # 第二步：尝试无阻塞获取底层锁，避免让路线程互相挤在一起。
            if self._lock.acquire(blocking=False):
                self._owner = thread_id
                if self._next == thread_id:
                    self._next = None
                    self._prefer_deadline = None
                    self._granted.set()
                return True

            if not blocking:
                return False
            sleep(0.001)

    def release(self) -> None:
        """释放底层锁。"""

        self._owner = None
        self._lock.release()

    def __enter__(self) -> "_OrderedLock":
        """支持 `with` 语法，`Condition` 内部依赖这个接口。"""

        self.acquire()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        """退出 `with` 代码块时归还锁。"""

        self.release()

    def locked(self) -> bool:
        """返回底层锁是否已被占用。"""

        return self._lock.locked()

    def _is_owned(self) -> bool:
        """`Condition` 会调用该方法判断调用线程是否持有这把锁。

        `notify_all()` 要求必须持锁才能唤醒别人，`Condition.wait()` 返回时
        也要靠这个结果决定如何重新获取锁。这里如实回答“当前线程是不是
        底层锁的持有者”，让 `Condition` 的锁协议保持完整。
        """

        return self._owner == get_ident()


def _wait_for(predicate, timeout: float = 5.0) -> bool:
    """轮询等待条件成立，避免用固定 `sleep` 猜测线程进度。"""

    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if predicate():
            return True
        sleep(0.005)
    return predicate()


def test_resource_scheduler_wakes_next_operation_after_queue_head_enters() -> None:
    """队首进入执行后，必须主动唤醒新的队首，否则后面的任务会一直排队。

    复现场景：先用两个后台线程把槽位占满，再让三个任务按顺序排队。
    此时把并发上限从 2 调到 5，一次唤醒后三个任务应该陆续进入。
    如果占用槽位后不唤醒新队首，除队首以外的任务会一直睡到下一次释放，
    表现就是“用户把并发数调大了，任务却半天不开始”。
    """

    # arrange：用可编排锁替换默认锁，让“编号靠后的等待者”先重新检查条件。
    scheduler = SerialResourceScheduler(max_concurrency=2)
    ordered_lock = _OrderedLock()
    scheduler._condition = Condition(ordered_lock)

    release_gate = Event()
    entered: list[int] = []
    entered_lock = Lock()
    idents: dict[int, int] = {}
    ident_lock = Lock()

    def holder() -> None:
        """占住一个槽位直到测试收尾。"""

        release_gate.wait(timeout=10)

    def waiter(index: int) -> None:
        """记录进入执行的编号，然后等待测试统一放行。"""

        with entered_lock:
            entered.append(index)
        release_gate.wait(timeout=10)

    def start_holder() -> None:
        scheduler.run("transcribe_video", holder)

    def start_waiter(index: int) -> None:
        # 先登记线程标识，测试后面要靠它指定谁先拿到锁。
        with ident_lock:
            idents[index] = get_ident()
        scheduler.run("transcribe_video", lambda: waiter(index))

    threads = []
    try:
        # 第一步：两个占位线程把并发上限 2 的槽位全部占满。
        for _ in range(2):
            holder_thread = Thread(target=start_holder, daemon=True)
            threads.append(holder_thread)
            holder_thread.start()

        group = scheduler._groups["transcribe_video"]
        assert _wait_for(lambda: group.active_count == 2)

        # 第二步：按顺序启动三个等待任务，并确认它们确实排在队列里，
        # 这样队列顺序与任务创建顺序一致。
        for index in range(3):
            thread = Thread(target=start_waiter, args=(index,), daemon=True)
            threads.append(thread)
            thread.start()
            assert _wait_for(lambda expected=index + 1: len(group.queue) == expected)

        # 第三步：指定第二个等待者先拿到锁，让它在队首还没进入时先重新判断，
        # 于是它会再次睡下；随后队首进入执行，调度器必须负责把它叫醒。
        ordered_lock.prefer_next(idents[1])

        # act：抬高并发上限，理论上三个等待任务都应该获得槽位。
        scheduler.set_limit("transcribe_video", 5)

        # assert：三个等待任务全部进入，且顺序仍然遵循先进先出。
        assert _wait_for(lambda: len(entered) == 3)
        with entered_lock:
            assert entered == [0, 1, 2]
    finally:
        release_gate.set()
        for thread in threads:
            thread.join(timeout=5)

    assert scheduler.limit_of("transcribe_video") == 5


def test_resource_scheduler_limit_can_be_adjusted_at_runtime() -> None:
    """运行中调整并发上限应对后续排队任务立即生效。"""

    scheduler = SerialResourceScheduler(max_concurrency=1)
    counter_lock = Lock()
    state = {"active": 0, "maximum": 0}
    gate = Event()

    def operation() -> None:
        with counter_lock:
            state["active"] += 1
            state["maximum"] = max(state["maximum"], state["active"])
        # 闸门等待时间必须明显长于下面的轮询时长，避免操作因为等待超时
        # 自己退出，把“并发上限是否生效”的断言变成竞态。
        gate.wait(timeout=30)
        with counter_lock:
            state["active"] -= 1

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [
            executor.submit(scheduler.run, "transcribe_video", operation)
            for _ in range(3)
        ]
        # 第一步：默认上限为 1，只有一个操作真正进入。
        sleep(0.05)
        assert scheduler.limit_of("transcribe_video") == 1
        assert state["maximum"] == 1

        # act：保持闸门关闭的情况下把上限提高到 3，其余操作应陆续进入。
        scheduler.set_limit("transcribe_video", 3)
        # 线程池是惰性创建的，这里轮询等待而不是假设线程已经就绪。
        deadline = monotonic() + 5
        while state["active"] < 3 and monotonic() < deadline:
            sleep(0.01)

        assert state["active"] == 3

        gate.set()
        for future in futures:
            future.result(timeout=5)

    assert scheduler.limit_of("transcribe_video") == 3
    assert state["maximum"] == 3


def test_resource_scheduler_rejects_nonpositive_limit_update() -> None:
    """运行时调整也必须拒绝零或负数，否则所有等待者会永久挂起。"""

    scheduler = SerialResourceScheduler(max_concurrency=1)

    with pytest.raises(ValueError, match="高资源任务并发数必须大于 0"):
        scheduler.set_limit("transcribe_video", 0)
