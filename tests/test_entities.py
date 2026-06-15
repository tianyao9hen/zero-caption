"""核心实体相关测试。

这些测试保护阶段 1 新增的领域对象行为，尤其是任务状态推进、
检查点顺序和错误记录这类后续容易被误改的逻辑。
"""

from pathlib import Path

import pytest

from core.domain.entities import Project, Task
from core.domain.enums import ProjectStatus, TaskCheckpoint, TaskStatus


def test_project_mark_imported_updates_status_and_timestamp(tmp_path):
    """项目导入后应进入 `IMPORTED` 状态，并刷新更新时间。"""

    # arrange：先创建一个最小项目实体。
    project = Project(
        project_id="project-1",
        source_video=tmp_path / "demo.mp4",
        source_language="auto",
        target_language="zh-CN",
        workspace_dir=tmp_path / "workspace",
    )
    original_updated_at = project.updated_at

    # act：把项目标记为已导入。
    project.mark_imported()

    # assert：状态和更新时间都应发生变化。
    assert project.status is ProjectStatus.IMPORTED
    assert project.updated_at >= original_updated_at
    assert project.last_error == ""


def test_task_start_progress_and_success_keep_checkpoint_monotonic():
    """任务推进时，检查点应只能前进不能后退。"""

    # arrange：创建一个还未执行的任务。
    task = Task(task_id="task-1", project_id="project-1", task_type="transcribe_video")

    # act：依次启动、更新进度并完成任务。
    task.start("开始识别")
    task.update_progress(
        progress=40,
        current_step="抽取音频",
        checkpoint=TaskCheckpoint.AUDIO_EXTRACTED,
        message="音频已准备好",
    )
    task.mark_succeeded("识别完成", checkpoint=TaskCheckpoint.TRANSCRIBED)

    # assert：任务应成功结束，并停留在最后一个成功检查点。
    assert task.status is TaskStatus.SUCCEEDED
    assert task.progress == 100
    assert task.checkpoint is TaskCheckpoint.TRANSCRIBED
    assert task.finished_at is not None
    assert task.message == "识别完成"


def test_task_rejects_checkpoint_rollback():
    """任务检查点不应允许从更后面的步骤回退到更前面的步骤。"""

    # arrange：先把任务推进到“已翻译”。
    task = Task(task_id="task-2", project_id="project-1", task_type="translate_subtitles")
    task.start("开始翻译")
    task.update_progress(
        progress=80,
        current_step="生成译文",
        checkpoint=TaskCheckpoint.TRANSLATED,
        message="译文生成中",
    )

    # act / assert：尝试回退到更早检查点时，应立刻抛错。
    with pytest.raises(ValueError):
        task.update_progress(
            progress=60,
            current_step="回退步骤",
            checkpoint=TaskCheckpoint.AUDIO_EXTRACTED,
            message="这一步不应被允许",
        )


def test_task_fail_records_error_and_finish_time():
    """任务失败时，应保留错误信息并记录结束时间。"""

    # arrange：创建并启动一个任务。
    task = Task(task_id="task-3", project_id="project-1", task_type="export_video")
    task.start("开始导出")

    # act：把任务标记为失败。
    task.mark_failed("导出路径不可写")

    # assert：失败状态应保留下来，方便后续恢复与诊断。
    assert task.status is TaskStatus.FAILED
    assert task.error_message == "导出路径不可写"
    assert task.finished_at is not None
    assert task.progress < 100


def test_task_rejects_progress_out_of_range():
    """任务进度必须保持在 0 到 100 之间。"""

    # arrange：创建一个任务。
    task = Task(task_id="task-4", project_id="project-1", task_type="create_project")

    # act / assert：非法进度值应被立即拦住，而不是带着脏状态继续执行。
    with pytest.raises(ValueError):
        task.update_progress(
            progress=120,
            current_step="错误进度",
            checkpoint=TaskCheckpoint.IMPORTED,
            message="超过 100 的进度值无效",
        )
