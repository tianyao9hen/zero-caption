"""整条视频流程进度映射测试。

这些测试保护“内部任务完成”和“用户的视频流程完成”之间的区别，
防止识别或翻译前置步骤再次把总进度提前推到 100%。
"""

from core.services.task_progress import overall_video_progress


def test_full_pipeline_reaches_100_when_translation_is_ready_to_download() -> None:
    """完整流程在译文可供用户下载时就应达到 100%。"""

    assert overall_video_progress(
        task_type="create_project",
        task_status="succeeded",
        task_progress=100,
    ) == 5
    assert overall_video_progress(
        task_type="transcribe_video",
        task_status="succeeded",
        task_progress=100,
    ) == 40
    assert overall_video_progress(
        task_type="translate_subtitles",
        task_status="succeeded",
        task_progress=100,
    ) == 100
    assert overall_video_progress(
        task_type="export_video",
        task_status="succeeded",
        task_progress=100,
    ) == 100


def test_transcribe_only_project_reaches_100_after_transcription() -> None:
    """仅识别模式没有翻译和导出步骤，识别成功就是最终完成。"""

    assert overall_video_progress(
        task_type="transcribe_video",
        task_status="succeeded",
        task_progress=100,
        processing_mode="transcribe_only",
    ) == 100


def test_download_operation_never_reduces_completed_pipeline_progress() -> None:
    """用户主动下载成品时，总进度应始终保持 100%。"""

    assert overall_video_progress(
        task_type="export_video",
        task_status="running",
        task_progress=96,
    ) == 100
    assert overall_video_progress(
        task_type="export_video",
        task_status="failed",
        task_progress=96,
    ) == 100
