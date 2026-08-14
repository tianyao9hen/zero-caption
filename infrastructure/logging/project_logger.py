"""项目级日志适配器。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path


@dataclass(slots=True)
class ProjectLogger:
    """把任务步骤和外部调用摘要追加到项目独立日志文件。"""

    project_dir: Path

    @property
    def log_path(self) -> Path:
        """返回项目日志文件路径。"""

        return self.project_dir / "logs" / "project.jsonl"

    def info(self, message: str, **context: object) -> None:
        """记录普通信息，不记录 API 密钥等敏感值。"""

        self._write("INFO", message, context)

    def error(self, message: str, **context: object) -> None:
        """记录错误摘要和可诊断上下文。"""

        self._write("ERROR", message, context)

    def _write(self, level: str, message: str, context: dict[str, object]) -> None:
        """以一行 JSON 追加日志，便于后续打包和脚本分析。"""

        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": level,
            "message": message,
            "context": context,
        }
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
