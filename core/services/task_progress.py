"""把内部任务进度转换成用户可见的整条视频流程进度。

这个模块属于核心层，只处理阶段与百分比之间的业务映射。
内部任务成功时自身进度会变成 100%，但任务页展示的是
`导入 -> 识别 -> 翻译` 自动流程进度，两者不能直接混用。用户主动下载
成品会另外产生一个导出任务，但不是翻译完成的前置条件。
"""

from __future__ import annotations

from core.domain.enums import ProcessingMode, ProjectStatus, TaskStatus


_SUCCEEDED_STAGE_PROGRESS = {
    "create_project": 5,
    "transcribe_video": 40,
    # 完整流程现在在翻译字幕完成后就已经具备“可下载成品”的条件。
    # 用户点击下载只是按需生成文件，不再是视频任务总进度的前置步骤，
    # 因此翻译任务成功时直接向用户报告 100%。
    "translate_subtitles": 100,
    "export_video": 100,
}


def overall_video_progress(
    *,
    task_type: str,
    task_status: str,
    task_progress: int,
    project_status: str = "",
    processing_mode: str = ProcessingMode.FULL_PIPELINE.value,
) -> int:
    """返回任务页应展示的整条视频流程进度。

    参数：
        task_type：当前内部任务类型。
        task_status：当前内部任务状态。
        task_progress：内部任务自己记录的进度。
        project_status：可选的项目总状态；项目完成时直接返回 100。
        processing_mode：处理模式；仅识别模式在识别成功后就是最终完成。

    返回：
        0 到 100 的用户可见总进度。项目在翻译完成后会被标记为完成，
        因此翻译任务和持久化历史都会显示 100%；单独的下载任务也会显示 100%。
    """

    if project_status == ProjectStatus.COMPLETED.value:
        return 100

    # 用户主动下载成品不属于“视频处理任务”的总进度。无论下载正在生成、
    # 已成功还是失败，字幕处理主链路都已经完成，因此总进度保持 100%，
    # 下载本身的结果由任务状态和消息单独表达。
    if task_type == "export_video":
        return 100

    if (
        processing_mode == ProcessingMode.TRANSCRIBE_ONLY.value
        and task_type == "transcribe_video"
        and task_status == TaskStatus.SUCCEEDED.value
    ):
        return 100

    if task_status == TaskStatus.SUCCEEDED.value:
        return _SUCCEEDED_STAGE_PROGRESS.get(task_type, task_progress)

    # 运行中任务已经按主链路区间上报进度。这里仍做边界规整，避免旧数据库
    # 或第三方调用传入异常百分比后让 Qt 进度条显示出范围外的值。
    return max(0, min(100, task_progress))
