"""面向任务的应用服务模块。

这个服务紧贴 `core` 层。UI 通过它发起视频处理、恢复、成品下载和字幕
修订，并查询持久化状态，而不是直接操作队列、仓储或基础设施适配器。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from core.domain.entities import Project
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
from core.ports.resource_scheduler import ResourceScheduler
from core.ports.workspace import ProjectWorkspace
from core.services.task_progress import overall_video_progress
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
    project_workspace: ProjectWorkspace | None = None
    resource_scheduler: ResourceScheduler | None = None
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

    def current_project_id(self) -> str | None:
        """返回这个服务实例最近处理的项目编号。

        桌面端为每条视频流程创建独立服务实例，因此主窗口可以用这个只读
        信息把新建项目与对应后台线程关联起来，支持运行中请求删除。
        """

        if self._latest_task_summary is None:
            return None
        return self._latest_task_summary.project_id or None

    def create_project(self, request: CreateProjectInput) -> CreateProjectResult:
        """把创建项目请求交给核心用例。"""

        result = self._require_usecase(self.create_project_usecase).execute(request)
        self._remember_task(result.task)
        return result

    def transcribe_video(self, request: TranscribeVideoInput) -> TranscribeVideoResult:
        """在受控的高资源槽位中执行本地识别用例。"""

        usecase = self._require_usecase(self.transcribe_video_usecase)
        result = self._run_resource_limited(
            "transcribe_video",
            lambda: usecase.execute(request),
        )
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
        """在受控的高资源槽位中执行视频导出用例。"""

        usecase = self._require_usecase(self.export_video_usecase)
        result = self._run_resource_limited(
            "export_video",
            lambda: usecase.execute(request),
        )
        self._remember_task(result.task)
        return result

    def reexport_project(
        self,
        request: ReexportProjectInput,
    ) -> ExportVideoResult:
        """在受控的高资源槽位中使用当前译文生成下载视频。"""

        usecase = self._require_usecase(self.reexport_project_usecase)
        result = self._run_resource_limited(
            "export_video",
            lambda: usecase.execute(request),
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
        调用方只提交一个结构化请求，具体步骤仍由独立用例负责，
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
                # 完整流程先把译文保存在项目工作区，用户稍后点击“下载成品”
                # 才选择外部目录。只有“仅识别”任务需要在创建时保存目标路径。
                output_path=(
                    request.output_path
                    if request.processing_mode is ProcessingMode.TRANSCRIBE_ONLY
                    else None
                ),
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
        """在已经存在的项目上继续识别和翻译步骤。"""

        # 第二步：本地探测、抽音频、识别并写出原文字幕。
        transcription = self.transcribe_video(
            TranscribeVideoInput(
                project_id=created.project.project_id,
                # 仅识别任务的主要成果就是原文字幕，因此把用户选择的
                # `.srt` 路径交给识别用例。完整流程不预先写用户目录，
                # 因此不能在这里误把兼容字段当成字幕路径。
                output_path=(
                    request.output_path
                    if request.processing_mode is ProcessingMode.TRANSCRIBE_ONLY
                    else None
                ),
            )
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

        # 第四步：译文字幕是自动处理流程的最终产物。此处只完成项目状态，
        # 不再自动复制或改写视频；用户稍后从任务页点击“下载成品”时，才会
        # 选择外部目录并显式调用导出用例。这样源视频始终只作为只读输入。
        project = created.project
        if self.project_repository is not None:
            persisted_project = self.project_repository.get_by_id(
                created.project.project_id
            )
            if persisted_project is None:
                raise RuntimeError("翻译完成后无法读取项目记录。")
            project = persisted_project
        project.export_mode = request.export_mode
        project.translation_context = (request.context or "").strip()
        project.mark_completed()
        if self.project_repository is not None:
            self.project_repository.save(project)
        created.project = project
        return ProcessVideoResult(
            project=created,
            transcription=transcription,
            translation=translation,
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
                    display_name=self._video_task_display_name(project),
                    source_video=project.source_video,
                    workspace_dir=project.workspace_dir,
                    output_path=project.output_path,
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
                    progress=(
                        overall_video_progress(
                            task_type=latest_task.task_type,
                            task_status=latest_task.status.value,
                            task_progress=latest_task.progress,
                            project_status=project.status.value,
                            processing_mode=project.processing_mode.value,
                        )
                        if latest_task
                        else 0
                    ),
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

    @staticmethod
    def _video_task_display_name(project: Project) -> str:
        """返回任务列表使用的可读名称，并兼容旧版本项目目录。

        新项目目录采用“视频名-随机后缀”，所以在目录名后补回原视频扩展名。
        旧项目的目录名等于内部项目编号，继续显示原视频文件名，避免历史任务
        突然变成难以识别的 UUID。
        """

        if (
            project.workspace_dir.name == project.project_id
            or project.workspace_dir.parent.name != "projects"
        ):
            return project.source_video.name
        return f"{project.workspace_dir.name}{project.source_video.suffix}"

    def delete_video_task(
        self,
        project_id: str,
        workspace_dir: str | None = None,
    ) -> None:
        """删除任意状态的视频项目记录及其项目目录。

        参数：
            project_id：任务列表选中的项目编号。
            workspace_dir：可选的已知项目目录。运行中删除第一次已移除
                数据库记录后，后台线程退出时可用它再次清理残留文件。

        副作用：
            会永久删除项目目录，并删除数据库中的项目、内部任务、字幕和
            导出记录。源视频和项目目录外的用户成果不会被删除。
        """

        project_repository = self._require_dependency(
            self.project_repository,
            "项目仓储",
        )
        project_workspace = self._require_dependency(
            self.project_workspace,
            "项目工作区",
        )
        project = project_repository.get_by_id(project_id)
        if project is None and not workspace_dir:
            raise ValueError(f"未找到项目：{project_id}")

        effective_workspace_dir = (
            project.workspace_dir if project is not None else workspace_dir
        )
        if effective_workspace_dir is None:
            raise RuntimeError("删除项目时缺少项目目录记录。")

        # 第一步：先删除严格校验过的项目目录。目录被占用时数据库记录仍保留，
        # 主窗口可以在后台任务退出后安全重试，不会留下无法定位的孤立文件。
        project_workspace.delete_project_structure(
            project_id,
            Path(effective_workspace_dir),
        )

        # 第二步：文件清理成功后再原子删除数据库聚合记录。
        # 第二次收尾调用时项目可能已经不存在，`delete` 返回 False 也属于成功。
        deleted = project_repository.delete(project_id)
        if project is not None and not deleted:
            raise RuntimeError("项目目录已删除，但数据库记录删除失败。")

        if (
            self._latest_task_summary is not None
            and self._latest_task_summary.project_id == project_id
        ):
            self._latest_task_summary = None

    def _remember_task(self, task) -> None:
        """把最近一次任务快照转成摘要，供界面层读取。"""

        self._latest_task_summary = TaskSummaryDTO(
            task_id=task.task_id,
            task_type=task.task_type,
            status=task.status.value,
            progress=overall_video_progress(
                task_type=task.task_type,
                task_status=task.status.value,
                task_progress=task.progress,
            ),
            current_step=task.current_step,
            message=task.message,
            project_id=task.project_id,
        )

    def _run_resource_limited(self, operation_name: str, operation):
        """通过可选调度端口执行高资源步骤并透传结果或异常。

        未注入调度器的轻量单元测试和脚本仍会直接执行原操作；桌面应用
        由容器注入同一个共享调度器，使不同 `TaskService` 实例也会竞争
        同一组资源槽位。
        """

        if self.resource_scheduler is None:
            return operation()
        return self.resource_scheduler.run(operation_name, operation)

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
