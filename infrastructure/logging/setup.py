"""日志配置辅助模块。

这个文件属于 infrastructure 层，因为它负责初始化 Python 的 logging 系统，
并把日志写到磁盘。其他层应该直接使用这里返回的 logger，而不是自己重复建 handler。
"""

from __future__ import annotations

from pathlib import Path
import logging


def configure_logging(log_dir: Path, level: str) -> logging.Logger:
    """创建或复用应用级 logger。

    参数：
        log_dir：日志文件要写入的目录。
        level：日志级别名称，例如 `"INFO"` 或 `"DEBUG"`。

    返回：
        一个已经配置好的 logger，供整个应用共享使用。
    """

    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("zero_caption")

    # `getattr` 可以把字符串形式的级别名，例如 `"INFO"`，转换成 `logging.INFO`。
    # 如果配置里写了未知值，就回退到 `logging.INFO`，避免因为拼写错误导致启动失败。
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    if not logger.handlers:
        # 日志处理器只添加一次。
        # 没有这个判断的话，重复执行启动装配会让同一条日志被重复写入文件。
        handler = logging.FileHandler(log_dir / "app.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger
