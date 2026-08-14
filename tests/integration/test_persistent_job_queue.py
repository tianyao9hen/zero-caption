"""持久化任务队列测试，保护领取、重试和异常恢复规则。"""

from infrastructure.storage.sqlite_db import SQLiteDatabase
from infrastructure.task.job_queue import PersistentJobQueue


def test_persistent_job_queue_claims_and_retries_jobs(tmp_path) -> None:
    """失败任务在重试次数内回到 pending，超过次数后才进入 failed。"""

    # arrange：最大重试次数设为 1，便于覆盖两次失败的边界。
    queue = PersistentJobQueue(SQLiteDatabase(tmp_path / "queue.sqlite3"))
    queued = queue.enqueue("process_video", {"source": "demo.mp4"}, max_retries=1)

    # act：第一次领取并失败，第二次领取后再次失败。
    claimed = queue.claim_next()
    first_status = queue.mark_failed(claimed.job_id, "网络暂时不可用")
    retried = queue.claim_next()
    second_status = queue.mark_failed(retried.job_id, "网络仍不可用")

    # assert：同一个任务保留 payload，并遵守重试上限。
    assert claimed.job_id == queued.job_id
    assert claimed.payload == {"source": "demo.mp4"}
    assert first_status == "pending"
    assert second_status == "failed"
    assert queue.claim_next() is None


def test_persistent_job_queue_recovers_running_jobs(tmp_path) -> None:
    """应用异常退出后，running 记录应重新进入 pending。"""

    queue = PersistentJobQueue(SQLiteDatabase(tmp_path / "queue.sqlite3"))
    queue.enqueue("process_video", {"source": "demo.mp4"})
    queue.claim_next()

    assert queue.recover_running() == 1
    recovered = queue.claim_next()
    assert recovered is not None
    assert recovered.status == "running"
