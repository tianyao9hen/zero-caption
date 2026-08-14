"""项目页面产物展示测试。

这些测试保护 UI 对可选流程结果的处理，确保仅识别模式不会因为缺少
翻译或视频导出结果而崩溃，也不会把成功任务错误显示为失败。
"""

from pathlib import Path

from PySide6.QtWidgets import QApplication

from core.domain.entities import Project, Task
from core.domain.enums import ProjectStatus, TaskCheckpoint
from core.dto.pipeline_dto import ProcessVideoResult
from core.dto.project_dto import CreateProjectResult
from core.dto.subtitle_dto import TranscribeVideoResult
from core.services.task_service import TaskService
from infrastructure.storage.workspace import WorkspaceManager
from ui.pages.projects_page import ProjectsPage


def test_projects_page_shows_local_transcription_artifacts(tmp_path) -> None:
    """仅识别结果应展示音频和原文字幕，并明确说明未导出视频。"""

    # arrange：构造已经完成本地识别的最小核心 DTO，避免测试真实模型。
    app = QApplication.instance() or QApplication([])
    workspace = WorkspaceManager(tmp_path / "workspace")
    project_dir = workspace.ensure_project_structure("project-local")
    source_video = tmp_path / "demo.mp4"
    audio_path = project_dir / "temp" / "source.wav"
    subtitle_path = project_dir / "subtitles" / "source.srt"
    project = Project(
        project_id="project-local",
        source_video=source_video,
        source_language="en",
        target_language="zh-CN",
        workspace_dir=project_dir,
        status=ProjectStatus.COMPLETED,
    )
    import_task = Task("task-import", project.project_id, "create_project")
    import_task.mark_succeeded("项目已导入", TaskCheckpoint.IMPORTED)
    transcription_task = Task(
        "task-transcribe",
        project.project_id,
        "transcribe_video",
    )
    transcription_task.mark_succeeded("识别完成", TaskCheckpoint.TRANSCRIBED)
    result = ProcessVideoResult(
        project=CreateProjectResult(project=project, task=import_task),
        transcription=TranscribeVideoResult(
            project_id=project.project_id,
            task=transcription_task,
            source_segments=[],
            audio_path=audio_path,
            subtitle_path=subtitle_path,
        ),
    )
    page = ProjectsPage(workspace, TaskService())

    # act
    page.show_result(result)

    # assert：页面直接显示本地产物路径，不要求翻译或导出结果存在。
    assert page.status_label.text() == ProjectStatus.COMPLETED.value
    assert page.audio_label.text() == str(Path(audio_path))
    assert page.subtitle_label.text() == str(Path(subtitle_path))
    assert page.output_label.text() == "未执行视频导出"
    page.deleteLater()
    app.processEvents()
