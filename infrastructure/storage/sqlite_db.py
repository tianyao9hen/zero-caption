"""SQLite 数据库基础设施。

这个模块属于基础设施层，只负责打开数据库连接、创建表和执行事务，
不决定项目何时开始处理或任务应该如何恢复。业务顺序仍由 `core` 层维护。
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator


class SQLiteDatabase:
    """管理本地 SQLite 文件，并在首次使用时创建当前版本的表结构。"""

    def __init__(self, path: Path) -> None:
        """保存数据库路径；真正的连接按操作创建，避免跨线程复用连接。"""

        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """提供一个自动提交或回滚的短连接上下文。"""

        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        """创建项目、任务、字幕和导出记录表。"""

        with self.connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    project_id TEXT PRIMARY KEY,
                    source_video TEXT NOT NULL,
                    source_language TEXT NOT NULL,
                    target_language TEXT NOT NULL,
                    workspace_dir TEXT NOT NULL,
                    source_fingerprint TEXT NOT NULL DEFAULT '',
                    translation_context TEXT NOT NULL DEFAULT '',
                    processing_mode TEXT NOT NULL DEFAULT 'full_pipeline',
                    export_mode TEXT NOT NULL DEFAULT 'soft_subtitle',
                    output_path TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_error TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL,
                    checkpoint TEXT,
                    current_step TEXT NOT NULL,
                    retry_count INTEGER NOT NULL,
                    message TEXT NOT NULL,
                    error_message TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    FOREIGN KEY(project_id) REFERENCES projects(project_id)
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id);
                CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
                CREATE TABLE IF NOT EXISTS subtitle_segments (
                    project_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    target_language TEXT NOT NULL DEFAULT '',
                    segment_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    start_ms INTEGER NOT NULL,
                    end_ms INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    language TEXT NOT NULL,
                    PRIMARY KEY(project_id, version, target_language, segment_id),
                    FOREIGN KEY(project_id) REFERENCES projects(project_id)
                );
                CREATE TABLE IF NOT EXISTS export_records (
                    export_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL,
                    source_video TEXT NOT NULL,
                    subtitle_path TEXT NOT NULL,
                    output_path TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(project_id)
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    job_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    retry_count INTEGER NOT NULL,
                    max_retries INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    claimed_at TEXT,
                    finished_at TEXT,
                    last_error TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, created_at);
                """
            )

            # 早期版本已经创建过 `projects` 表。`CREATE TABLE IF NOT EXISTS`
            # 不会自动给旧表补列，因此这里执行小型迁移，让用户原有数据库
            # 可以直接升级，不需要删除任务历史或手工运行 SQL。
            self._ensure_columns(
                connection,
                table_name="projects",
                columns={
                    "translation_context": "TEXT NOT NULL DEFAULT ''",
                    "processing_mode": (
                        "TEXT NOT NULL DEFAULT 'full_pipeline'"
                    ),
                    "export_mode": "TEXT NOT NULL DEFAULT 'soft_subtitle'",
                    "output_path": "TEXT",
                },
            )

    @staticmethod
    def _ensure_columns(
        connection: sqlite3.Connection,
        table_name: str,
        columns: dict[str, str],
    ) -> None:
        """为旧版 SQLite 表补充当前版本需要的列。

        参数：
            connection：当前初始化事务使用的数据库连接。
            table_name：需要检查的表名，只能来自模块内固定常量。
            columns：列名到 SQLite 类型声明的映射。

        该方法只在应用启动建库时运行，不负责业务数据迁移。列名和声明均由
        代码内常量提供，不接收用户输入，因此可以安全拼入 `ALTER TABLE`。
        """

        existing_columns = {
            row["name"]
            for row in connection.execute(
                f"PRAGMA table_info({table_name})"
            ).fetchall()
        }
        for column_name, declaration in columns.items():
            if column_name in existing_columns:
                continue
            connection.execute(
                f"ALTER TABLE {table_name} ADD COLUMN "
                f"{column_name} {declaration}"
            )
