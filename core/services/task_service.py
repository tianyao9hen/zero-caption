"""面向任务的应用服务模块。

这个服务紧贴 `core` 层。UI 通过它发起视频处理、恢复、重新导出和字幕
修订，并查询持久化状态，而不是直接操作队列、仓储或基础设施适配器。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.domain.enums import ProcessingMode, ProjectStatus, TaskStatus
from core.dto.project_dto import CreateProjectInput, CreateProjectResult
from core.dto.pipeline_dto import ProcessVideoInput, ProcessVideoResult
from core.dto.subtitle_dto import (
    EditSubtitleTranslationInput,
    RetranslateSubtitleInput,
    SubtitleTranslationItemDTO,
    SubtitleTranslationUpdateResult,
    TranscribeVideoInput,
    TranscribeVideoResult,
    TranslateSubtitlesInput,
    TranslateSubtitlesResult,
)
from core.dto.task_dto import (
    ExportVideoInput,
    ExportVideoResult,
    ReexportProjectInput,
    TaskSummaryDTO,
    VideoTaskHistoryDTO,
)
from core.ports.repository import (
    ProjectRepository,
    SubtitleRepository,
    TaskRepository,
)
from core.usecases.create_project import CreateProject
from core.usecases.export_video import ExportVideo
from core.usecases.reexport_project import ReexportProject
from core.usecases.revise_subtitle_translation import ReviseSubtitleTranslation
from core.usecases.transcribe_video import TranscribeVideo
from core.usecases.translate_subtitles import TranslateSubtitles


@dataclass(slots=True)
class TaskService:
    """为任务相关状态提供一个简单的访问接口。"""

    create_project_usecase: CreateProject | None = None
    transcribe_video_usecase: TranscribeVideo | None = None
    translate_subtitles_usecase: TranslateSubtitles | None = None
    export_video_usecase: ExportVideo | None = None
    reexport_project_usecase: ReexportProject | None = None
    revise_subtitle_translation_usecase: ReviseSubtitleTranslation | None = None
    project_repository: ProjectRepository | None = None
    task_repository: TaskRepository | None = None
    subtitle_repository: SubtitleRepository | None = None
    _latest_task_summary: TaskSummaryDTO | None = field(default=None, init=False)

    def summary(self) -> str:
        """返回一段给 UI 展示的简短任务摘要。

        状态栏和任务页都会调用这个方法。当前先返回普通字符串，
        这样在完整任务系统尚未实现前，第一版界面仍然容易展示和调试。
        """

        if self._latest_task_summary is None:
            return "暂无活动任务"
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

    def reexport_project(
        self,
        request: ReexportProjectInput,
    ) -> ExportVideoResult:
        """使用已有项目的当前译文重新导出视频。"""

        result = self._require_usecase(self.reexport_project_usecase).execute(
            request
        )
        self._remember_task(result.task)
        return result

    def list_subtitle_translations(
        self,
        project_id: str,
    ) -> list[SubtitleTranslationItemDTO]:
        """按原字幕顺序返回项目的原文和译文配对结果。

        该查询只读取结构化字幕，不读取视频或音频。尚未产生译文的原文也会
        返回，界面可以据此明确展示“尚无译文”，但不会允许把它当成结果修订。
        """

        project_repository = self._require_dependency(
            self.project_repository,
            "项目仓储",
        )
        subtitle_repository = self._require_dependency(
            self.subtitle_repository,
            "字幕仓储",
        )
        project = project_repository.get_by_id(project_id)
        if project is None:
            raise ValueError(f"未找到项目：{project_id}")

        source_segments = subtitle_repository.get_source_segments(project_id)
        translated_by_id = {
            segment.segment_id: segment
            for segment in subtitle_repository.get_translated_segments(
                project_id,
                project.target_language,
            )
        }
        total_segments = len(source_segments)
        return [
            SubtitleTranslationItemDTO(
                project_id=project_id,
                segment_id=source.segment_id,
                current_index=index,
                total_segments=total_segments,
                start_ms=source.start_ms,
                end_ms=source.end_ms,
                source_text=source.text,
                translated_text=(
                    translated_by_id[source.segment_id].text
                    if source.segment_id in translated_by_id
                    else ""
                ),
            )
            for index, source in enumerate(source_segments, start=1)
        ]

    def edit_subtitle_translation(
        self,
        request: EditSubtitleTranslationInput,
    ) -> SubtitleTranslationUpdateResult:
        """保存一条用户编辑的译文，并记录最近任务摘要。"""

        result = self._require_usecase(
            self.revise_subtitle_translation_usecase
        ).save_edit(request)
        self._remember_task(result.task)
        return result

    def retranslate_subtitle(
        self,
        request: RetranslateSubtitleInput,
    ) -> SubtitleTranslationUpdateResult:
        """让当前翻译引擎只重新翻译指定的一条字幕。"""

        result = self._require_usecase(
            self.revise_subtitle_translation_usecase
        ).retranslate(request)
        self._remember_task(result.task)
        return result

    def process_video(self, request: ProcessVideoInput) -> ProcessVideoResult:
        """按请求模式执行本地识别或完整字幕处理流程。

        这个方法是 UI 和命令行入口共享的核心编排入口。
        调用方只提交一个结构化请求，具体步骤仍由四个独立用例负责，
        因此页面层不需要复制主链路顺序或处理失败状态。
        """

        # 第一步：创建项目并建立项目级工作目录。
        created = self.create_project(
            CreateProjectInput(
                source_video=request.source_video,
                source_language=request.source_language,
                target_language=request.target_language,
                workspace_dir=request.workspace_dir,
                translation_context=(request.context or "").strip(),
                processing_mode=request.processing_mode,
                export_mode=request.export_mode,
                output_path=request.output_path,
            )
        )

        return self._continue_project(created, request)

    def retry_video(self, project_id: str) -> ProcessVideoResult:
        """从已有项目的稳定产物继续一次失败或待恢复的视频任务。

        该方法不会创建新项目。识别、翻译用例会分别检查音频、原字幕和
        逐句译文缓存，因此已经成功的高成本步骤不会重复执行。
        """

        project_repository = self._require_dependency(
            self.project_repository,
            "项目仓储",
        )
        task_repository = self._require_dependency(
            self.task_repository,
            "任务仓储",
        )
        project = project_repository.get_by_id(project_id)
        if project is None:
            raise ValueError(f"未找到项目：{project_id}")

        tasks = task_repository.list_by_project(project_id)
        latest_task = tasks[0] if tasks else None
        can_retry = project.status is ProjectStatus.FAILED or (
            project.status is ProjectStatus.PROCESSING
            and latest_task is not None
            and latest_task.status is TaskStatus.PENDING
        )
        if not can_retry:
            raise ValueError("只有失败或应用重启后待恢复的任务可以继续。")
        if latest_task is None:
            raise RuntimeError("项目没有可用于恢复的任务记录。")

        # 第一步：恢复结果仍沿用最初的导入任务和项目编号。
        # `ProcessVideoResult` 因而可以继续被项目页和命令行入口共同消费。
        import_task = next(
            (task for task in tasks if task.task_type == "create_project"),
            None,
        )
        if import_task is None:
            raise RuntimeError("项目缺少原始导入任务，无法安全恢复。")

        # 第二步：所有恢复前置条件满足后再增加原失败任务的重试次数。
        # 历史页会聚合项目内最大值，因此后续新任务不会把计数重新显示为零。
        latest_task.increment_retry()
        latest_task.message = f"用户已请求第 {latest_task.retry_count} 次继续处理"
        task_repository.save(latest_task)

        project.mark_processing()
        project_repository.save(project)
        request = ProcessVideoInput(
            source_video=project.source_video,
            source_language=project.source_language,
            target_language=project.target_language,
            workspace_dir=project.workspace_dir,
            context=project.translation_context or None,
            output_path=project.output_path,
            export_mode=project.export_mode,
            processing_mode=project.processing_mode,
        )
        return self._continue_project(
            CreateProjectResult(project=project, task=import_task),
            request,
        )

    def _continue_project(
        self,
        created: CreateProjectResult,
        request: ProcessVideoInput,
    ) -> ProcessVideoResult:
        """在已经存在的项目上继续识别、翻译和导出步骤。"""

        # 第二步：本地探测、抽音频、识别并写出原文字幕。
        transcription = self.transcribe_video(
            TranscribeVideoInput(project_id=created.project.project_id)
        )

        # 仅识别模式到这里已经得到正式原文字幕。此分支不会触碰翻译器或
        # 视频导出器，因此没有大模型配置和网络连接时也能正常完成任务。
        if request.processing_mode is ProcessingMode.TRANSCRIBE_ONLY:
            if transcription.subtitle_path is None:
                raise RuntimeError("识别完成后没有生成原文字幕文件。")

            project_repository = self._require_dependency(
                self.project_repository,
                "项目仓储",
            )
            project = project_repository.get_by_id(created.project.project_id)
            if project is None:
                raise RuntimeError("识别完成后无法读取项目记录。")
            project.mark_completed()
            project_repository.save(project)
            created.project = project
            return ProcessVideoResult(
                project=created,
                transcription=transcription,
            )

        # 第三步：只把字幕文本发送给翻译端口，并写出译文字幕。
        translation = self.translate_subtitles(
            TranslateSubtitlesInput(
                project_id=created.project.project_id,
                source_language=request.source_language,
                target_language=request.target_language,
                context=request.context,
            )
        )
        if translation.subtitle_path is None:
            raise RuntimeError("翻译完成后没有生成正式字幕文件。")

        # 第四步：默认把成品放到项目 exports 目录，调用方也可以显式指定路径。
        output_path = request.output_path
        if output_path is None:
            output_path = (
                created.project.workspace_dir
                / "exports"
                / request.source_video.name
            )
        created.project.output_path = output_path
        created.project.export_mode = request.export_mode
        created.project.translation_context = (request.context or "").strip()
        created.project.touch()
        # 完整桌面装配会注入项目仓储，从而在导出前保存恢复参数。
        # 少量只验证用例顺序的轻量测试没有查询依赖，仍可依靠同一个内存实体
        # 继续执行，不应为此强制它们装配与测试目标无关的仓储入口。
        if self.project_repository is not None:
            self.project_repository.save(created.project)
        export = self.export_video(
            ExportVideoInput(
                project_id=created.project.project_id,
                source_video=request.source_video,
                subtitle_path=translation.subtitle_path,
                output_path=output_path,
                mode=request.export_mode,
            )
        )
        return ProcessVideoResult(
            project=created,
            transcription=transcription,
            translation=translation,
            export=export,
        )

    def list_video_tasks(self, limit: int = 50) -> list[VideoTaskHistoryDTO]:
        """按视频项目聚合并返回最近任务记录。

        参数：
            limit：最多返回多少个视频项目，必须大于零。

        返回：
            每个项目只出现一次，并附带该项目最近内部任务的状态。

        这个查询只整理仓储数据，不执行识别、翻译或文件写入。
        因此任务页可以在应用重启后恢复历史视图，又不会直接依赖 SQLite。
        """

        if limit <= 0:
            raise ValueError("任务历史数量必须大于 0。")

        project_repository = self._require_dependency(
            self.project_repository,
            "项目仓储",
        )
        task_repository = self._require_dependency(
            self.task_repository,
            "任务仓储",
        )

        # 第一步：项目仓储已经按更新时间倒序返回记录，先截断可以避免
        # 历史数量很大时为不可见项目继续读取任务明细。
        projects = project_repository.list_all()[:limit]
        history: list[VideoTaskHistoryDTO] = []

        # 第二步：同一个视频会产生多个内部任务，界面只取最新一条作为摘要。
        # 这样用户看到的是“一个视频任务”，而不是四个彼此割裂的技术步骤。
        for project in projects:
            tasks = task_repository.list_by_project(project.project_id)
            latest_task = tasks[0] if tasks else None
            history.append(
                VideoTaskHistoryDTO(
                    project_id=project.project_id,
                    source_video=project.source_video,
                    workspace_dir=project.workspace_dir,
                    source_language=project.source_language,
                    target_language=project.target_language,
                    processing_mode=project.processing_mode.value,
                    export_mode=project.export_mode.value,
                    project_status=project.status.value,
                    task_id=latest_task.task_id if latest_task else "",
                    task_type=latest_task.task_type if latest_task else "",
                    task_status=(
                        latest_task.status.value if latest_task else "pending"
                    ),
                    progress=latest_task.progress if latest_task else 0,
                    checkpoint=(
                        latest_task.checkpoint.value
                        if latest_task and latest_task.checkpoint
                        else ""
                    ),
                    current_step=latest_task.current_step if latest_task else "",
                    message=latest_task.message if latest_task else "",
                    error_message=(
                        latest_task.error_message if latest_task else ""
                    ),
                    retry_count=max(
                        (task.retry_count for task in tasks),
                        default=0,
                    ),
                    created_at=project.created_at,
                    updated_at=project.updated_at,
                )
            )
        return history

    def _remember_task(self, task) -> None:
        """把最近一次任务快照转成摘要，供界面层读取。"""

        self._latest_task_summary = TaskSummaryDTO(
            task_id=task.task_id,
            task_type=task.task_type,
            status=task.status.value,
            progress=task.progress,
            current_step=task.current_step,
            message=task.message,
            project_id=task.project_id,
        )

    def _require_usecase(self, usecase):
        """确保服务在真正调用前已经拿到了对应用例。"""

        if usecase is None:
            raise RuntimeError("当前 TaskService 尚未装配对应用例。")
        return usecase

    def _require_dependency(self, dependency, name: str):
        """确保可选的编排依赖已由应用容器注入。"""

        if dependency is None:
            raise RuntimeError(f"当前 TaskService 尚未装配{name}。")
        return dependency
