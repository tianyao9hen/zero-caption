"""日志配置辅助模块。

这个文件属于 infrastructure 层，因为它负责初始化 Python 的 logging 系统，
并把日志写到磁盘。其他层应该直接使用这里返回的 logger，而不是自己重复建 handler。
"""

from __future__ import annotations

from pathlib import Path
import logging


def configure_logging(
    log_dir: Path,
    level: str,
    logger: logging.Logger | None = None,
) -> logging.Logger:
    """创建或复用应用级 logger。

    参数：
        log_dir：日志文件要写入的目录。
        level：日志级别名称，例如 `"INFO"` 或 `"DEBUG"`。
        logger：可选的现有日志对象。工作区切换时传入它，可以关闭旧目录中的
            文件句柄并继续复用同一个对象。

    返回：
        一个已经配置好的 logger，供整个应用共享使用。
    """

    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logger or logging.getLogger("zero_caption")

    # `getattr` 可以把字符串形式的级别名，例如 `"INFO"`，转换成 `logging.INFO`。
    # 如果配置里写了未知值，就回退到 `logging.INFO`，避免因为拼写错误导致启动失败。
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    target = (log_dir / "app.log").resolve()

    # 工作区变化时必须关闭旧 `FileHandler`，否则 Windows 会一直占用旧日志文件，
    # 用户即使确认删除也无法移除旧工作区。控制台等非文件处理器继续保留。
    target_handler_exists = False
    for handler in tuple(logger.handlers):
        if not isinstance(handler, logging.FileHandler):
            continue
        if Path(handler.baseFilename).resolve() == target:
            target_handler_exists = True
            continue
        logger.removeHandler(handler)
        handler.close()

    if not target_handler_exists:
        handler = logging.FileHandler(log_dir / "app.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger
