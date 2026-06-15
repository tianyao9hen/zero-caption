"""稳定枚举值相关测试。

这些测试用于防止枚举字符串值被意外改名，因为别的模块可能会依赖它们做持久化
或界面展示。阶段 1 额外把导出模式和任务检查点也纳入保护范围，
避免后续主链路扩展时把稳定协议改散。
"""

from core.domain.enums import ExportMode, ProjectStatus, TaskCheckpoint, TaskStatus


def test_project_status_values():
    """项目状态枚举值应保持稳定。"""

    assert ProjectStatus.NEW.value == "new"
    assert ProjectStatus.COMPLETED.value == "completed"


def test_task_status_values():
    """任务状态枚举值应保持稳定。"""

    assert TaskStatus.PENDING.value == "pending"
    assert TaskStatus.SUCCEEDED.value == "succeeded"


def test_export_mode_values():
    """导出模式枚举值应和配置层语义保持一致。"""

    assert ExportMode.SOFT_SUBTITLE.value == "soft_subtitle"
    assert ExportMode.BURN_IN.value == "burn_in"


def test_task_checkpoint_values():
    """任务检查点枚举值应覆盖阶段 1 固定下来的主链路步骤。"""

    assert TaskCheckpoint.IMPORTED.value == "imported"
    assert TaskCheckpoint.AUDIO_EXTRACTED.value == "audio_extracted"
    assert TaskCheckpoint.TRANSCRIBED.value == "transcribed"
    assert TaskCheckpoint.TRANSLATED.value == "translated"
    assert TaskCheckpoint.COMPOSED.value == "composed"
    assert TaskCheckpoint.EXPORTED.value == "exported"
