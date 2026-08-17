"""高资源任务调度器测试。

这些测试保护多视频并发时最重要的资源边界：普通流程可以由多个后台线程
同时推进，但识别和视频导出等高资源操作不能同时占满电脑。
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from time import sleep

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
