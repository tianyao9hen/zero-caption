"""面向任务的应用服务模块。

这个服务紧贴 core 层。UI 应该通过这种服务获取任务状态，而不是直接操作队列。
当前骨架里的行为还很少，但它已经标出了未来任务创建、进度更新和状态查询的入口位置。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.dto.project_dto import CreateProjectInput, CreateProjectResult
from core.dto.subtitle_dto import (
    TranscribeVideoInput,
    TranscribeVideoResult,
    TranslateSubtitlesInput,
    TranslateSubtitlesResult,
)
from core.dto.task_dto import ExportVideoInput, ExportVideoResult, TaskSummaryDTO
from core.usecases.create_project import CreateProject
from core.usecases.export_video import ExportVideo
from core.usecases.transcribe_video import TranscribeVideo
from core.usecases.translate_subtitles import TranslateSubtitles


@dataclass(slots=True)
class TaskService:
    """为任务相关状态提供一个简单的访问接口。"""

    create_project_usecase: CreateProject | None = None
    transcribe_video_usecase: TranscribeVideo | None = None
    translate_subtitles_usecase: TranslateSubtitles | None = None
    export_video_usecase: ExportVideo | None = None
    _latest_task_summary: TaskSummaryDTO | None = field(default=None, init=False)

    def summary(self) -> str:
        """返回一段给 UI 展示的简短任务摘要。

        状态栏和任务页都会调用这个方法。当前先返回普通字符串，
        这样在完整任务系统尚未实现前，第一版界面仍然容易展示和调试。
        """

        if self._latest_task_summary is None:
            return "No active task"
        summary = self._latest_task_summary
        return f"{summary.task_type}: {summary.message} ({summary.progress}%)"

    def create_project(self, request: CreateProjectInput) -> CreateProjectResult:
        """把创建项目请求交给核心用例。"""

        result = self._require_usecase(self.create_project_usecase).execute(request)
        self._remember_task(result.task)
        return result

    def transcribe_video(self, request: TranscribeVideoInput) -> TranscribeVideoResult:
        """把识别请求交给核心用例。"""

        result = self._require_usecase(self.transcribe_video_usecase).execute(request)
        self._remember_task(result.task)
        return result

    def translate_subtitles(
        self,
        request: TranslateSubtitlesInput,
    ) -> TranslateSubtitlesResult:
        """把翻译请求交给核心用例。"""

        result = self._require_usecase(self.translate_subtitles_usecase).execute(request)
        self._remember_task(result.task)
        return result

    def export_video(self, request: ExportVideoInput) -> ExportVideoResult:
        """把导出请求交给核心用例。"""

        result = self._require_usecase(self.export_video_usecase).execute(request)
        self._remember_task(result.task)
        return result

    def _remember_task(self, task) -> None:
        """把最近一次任务快照转成摘要，供界面层读取。"""

        self._latest_task_summary = TaskSummaryDTO(
            task_id=task.task_id,
            task_type=task.task_type,
            status=task.status.value,
            progress=task.progress,
            current_step=task.current_step,
            message=task.message,
        )

    def _require_usecase(self, usecase):
        """确保服务在真正调用前已经拿到了对应用例。"""

        if usecase is None:
            raise RuntimeError("当前 TaskService 尚未装配对应用例。")
        return usecase
