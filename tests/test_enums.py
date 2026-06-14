"""稳定枚举值相关测试。

这些测试用于防止枚举字符串值被意外改名，因为别的模块可能会依赖它们做持久化
或界面展示。
"""

from core.domain.enums import ProjectStatus, TaskStatus


def test_project_status_values():
    """项目状态枚举值应保持稳定。"""

    assert ProjectStatus.NEW.value == "new"
    assert ProjectStatus.COMPLETED.value == "completed"


def test_task_status_values():
    """任务状态枚举值应保持稳定。"""

    assert TaskStatus.PENDING.value == "pending"
    assert TaskStatus.SUCCEEDED.value == "succeeded"
