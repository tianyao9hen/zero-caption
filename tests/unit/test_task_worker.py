"""worker 单元测试，保护成功和失败都能回写持久化状态。"""

from infrastructure.storage.sqlite_db import SQLiteDatabase
from infrastructure.task.job_queue import PersistentJobQueue
from infrastructure.task.worker import TaskWorker


def test_task_worker_marks_successful_job(tmp_path) -> None:
    """handler 正常返回时，队列任务应进入 succeeded。"""

    queue = PersistentJobQueue(SQLiteDatabase(tmp_path / "worker.sqlite3"))
    job = queue.enqueue("demo", {"value": 1})
    worker = TaskWorker(queue)
    handled: list[str] = []

    assert worker.run_once(lambda item: handled.append(item.job_id)) is True
    assert handled == [job.job_id]
    assert queue.list_by_status("succeeded")[0].job_id == job.job_id


def test_task_worker_requeues_failed_job_until_retry_limit(tmp_path) -> None:
    """handler 抛错时，worker 应让队列根据重试策略决定最终状态。"""

    queue = PersistentJobQueue(SQLiteDatabase(tmp_path / "worker.sqlite3"))
    job = queue.enqueue("demo", {}, max_retries=0)
    worker = TaskWorker(queue)

    def failing_handler(_job) -> None:
        """用固定异常模拟不可重试的处理失败。"""

        raise RuntimeError("失败")

    assert worker.run_once(failing_handler) is True
    failed = queue.list_by_status("failed")
    assert len(failed) == 1
    assert failed[0].job_id == job.job_id
    assert failed[0].last_error == "失败"
