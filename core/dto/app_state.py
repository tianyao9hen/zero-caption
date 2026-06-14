"""应用层之间共享的 DTO 模块。

DTO 是 Data Transfer Object 的缩写，在这个项目里表示一种轻量数据对象，
用来在不同层之间传递已经整理好的状态，而不是在对象上附加业务行为。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class AppStateDTO:
    """应用级 UI 状态的最小快照。"""

    current_page: str = "projects"
    task_summary: str = "No active task"
    log_summary: str = "No recent events"
