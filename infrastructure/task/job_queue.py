"""任务队列基础设施实现。

这个文件同时保留早期测试使用的内存队列，并提供 SQLite 持久化队列。
它属于 `infrastructure` 层，因为“队列如何保存和领取”是执行细节，
不是业务规则。桌面主流程目前采用用户显式操作和后台线程，持久化 worker
尚未接管自动调度。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
from uuid import uuid4

from infrastructure.storage.sqlite_db import SQLiteDatabase


@dataclass(slots=True)
class JobQueue:
    """按进入顺序保存待处理任务。

    标准库里的 deque 很适合做两端追加和弹出操作。
    它只用于轻量测试和兼容早期调用方，桌面恢复状态以 SQLite 为准。
    """

    _queue: deque = field(default_factory=deque)

    def enqueue(self, job) -> None:
        """把一个任务对象追加到队列尾部。"""

        self._queue.append(job)

    def size(self) -> int:
        """返回当前队列中的任务数量。"""

        return len(self._queue)


@dataclass(slots=True)
class PersistentJob:
    """描述一条可以在应用重启后继续领取的队列记录。"""

    job_id: str
    job_type: str
    payload: dict[str, object]
    status: str
    retry_count: int
    max_retries: int
    created_at: datetime
    claimed_at: datetime | None = None
    finished_at: datetime | None = None
    last_error: str = ""


@dataclass(slots=True)
class PersistentJobQueue:
    """使用 SQLite 保存待处理任务，并提供领取、完成、失败重试操作。"""

    database: SQLiteDatabase

    def enqueue(
        self,
        job_type: str,
        payload: dict[str, object],
        max_retries: int = 2,
    ) -> PersistentJob:
        """写入一条待处理任务，返回包含稳定编号的队列记录。"""

        if max_retries < 0:
            raise ValueError("最大重试次数不能小于 0。")
        job = PersistentJob(
            job_id=f"job-{uuid4().hex}",
            job_type=job_type,
            payload=dict(payload),
            status="pending",
            retry_count=0,
            max_retries=max_retries,
            created_at=datetime.now(UTC),
        )
        with self.database.connection() as connection:
            connection.execute(
                """
                INSERT INTO jobs (
                    job_id, job_type, payload_json, status, retry_count,
                    max_retries, created_at, claimed_at, finished_at, last_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.job_id,
                    job.job_type,
                    json.dumps(job.payload, ensure_ascii=False),
                    job.status,
                    job.retry_count,
                    job.max_retries,
                    job.created_at.isoformat(),
                    None,
                    None,
                    "",
                ),
            )
        return job

    def claim_next(self) -> PersistentJob | None:
        """原子领取最早的待处理任务，避免两个 worker 同时执行同一条记录。"""

        with self.database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM jobs WHERE status = 'pending' ORDER BY created_at LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            claimed_at = datetime.now(UTC).isoformat()
            connection.execute(
                "UPDATE jobs SET status = 'running', claimed_at = ? WHERE job_id = ?",
                (claimed_at, row["job_id"]),
            )
            row = dict(row)
            row["status"] = "running"
            row["claimed_at"] = claimed_at
        return self._from_row(row)

    def mark_succeeded(self, job_id: str) -> None:
        """把已执行成功的任务标记为完成。"""

        with self.database.connection() as connection:
            connection.execute(
                "UPDATE jobs SET status = 'succeeded', finished_at = ? WHERE job_id = ?",
                (datetime.now(UTC).isoformat(), job_id),
            )

    def mark_failed(self, job_id: str, error: str, retryable: bool = True) -> str:
        """记录失败并按剩余次数决定回到 pending 还是进入 failed。"""

        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT retry_count, max_retries FROM jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"未找到队列任务：{job_id}")
            retry_count = int(row["retry_count"]) + 1
            status = "pending" if retryable and retry_count <= row["max_retries"] else "failed"
            connection.execute(
                """
                UPDATE jobs
                SET status = ?, retry_count = ?, last_error = ?, finished_at = ?
                WHERE job_id = ?
                """,
                (
                    status,
                    retry_count,
                    error,
                    None if status == "pending" else datetime.now(UTC).isoformat(),
                    job_id,
                ),
            )
        return status

    def recover_running(self) -> int:
        """把异常退出留下的 running 任务重新放回待处理队列。"""

        with self.database.connection() as connection:
            cursor = connection.execute(
                "UPDATE jobs SET status = 'pending', claimed_at = NULL WHERE status = 'running'"
            )
        return cursor.rowcount

    def list_by_status(self, status: str) -> list[PersistentJob]:
        """按状态读取队列任务，便于启动诊断和任务页展示。"""

        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY created_at",
                (status,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    @staticmethod
    def _from_row(row) -> PersistentJob:
        """把数据库行转换成队列领域记录。"""

        values = dict(row)
        return PersistentJob(
            job_id=values["job_id"],
            job_type=values["job_type"],
            payload=json.loads(values["payload_json"]),
            status=values["status"],
            retry_count=int(values["retry_count"]),
            max_retries=int(values["max_retries"]),
            created_at=datetime.fromisoformat(values["created_at"]),
            claimed_at=(
                datetime.fromisoformat(values["claimed_at"])
                if values["claimed_at"]
                else None
            ),
            finished_at=(
                datetime.fromisoformat(values["finished_at"])
                if values["finished_at"]
                else None
            ),
            last_error=values["last_error"],
        )
