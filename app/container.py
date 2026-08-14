"""桌面应用骨架的简单依赖容器。

容器属于 app 层，负责把具体实现装配起来再交给 UI 使用。
这样页面类就不需要自己直接创建基础设施对象。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import TYPE_CHECKING

from config.settings import Settings
from core.ports.asr import AsrEngine
from core.ports.repository import (
    ExportRecordRepository,
    ProjectRepository,
    SubtitleRepository,
    TaskRepository,
)
from core.services.task_service import TaskService
from core.usecases.create_project import CreateProject
from core.usecases.export_video import ExportVideo
from core.usecases.transcribe_video import TranscribeVideo
from core.usecases.translate_subtitles import TranslateSubtitles
from infrastructure.asr import FasterWhisperEngine
from infrastructure.media.ffmpeg import FFmpegAdapter
from infrastructure.media.ffprobe import FFprobeAdapter
from infrastructure.storage.fingerprint import Sha256FileFingerprintCalculator
from infrastructure.storage.workspace import WorkspaceManager
from infrastructure.storage.sqlite_db import SQLiteDatabase
from infrastructure.storage.sqlite_repositories import (
    SQLiteExportRecordRepository,
    SQLiteProjectRepository,
    SQLiteSubtitleRepository,
    SQLiteTaskRepository,
)
from infrastructure.task.job_queue import PersistentJobQueue
from infrastructure.task.progress_bus import ProgressBus
from infrastructure.subtitle.aligner import SubtitleAligner
from infrastructure.subtitle.formatter import SubtitleFormatter
from infrastructure.subtitle.srt_writer import SrtWriter
from infrastructure.export import (
    BurnInExporter,
    CompositeVideoExporter,
    SoftSubtitleExporter,
)
from core.domain.enums import ExportMode
from infrastructure.translation.batch_builder import TranslationBatchBuilder
from infrastructure.translation.openai_translator import OpenAICompatibleTranslator

if TYPE_CHECKING:
    from ui.windows.main_window import MainWindow


@dataclass(slots=True)
class AppContainer:
    """基于共享依赖创建应用服务和窗口对象。"""

    settings: Settings
    workspace: WorkspaceManager
    logger: logging.Logger
    database: SQLiteDatabase | None = None
    project_repository: ProjectRepository | None = None
    task_repository: TaskRepository | None = None
    subtitle_repository: SubtitleRepository | None = None
    export_record_repository: ExportRecordRepository | None = None
    job_queue: PersistentJobQueue | None = None
    progress_bus: ProgressBus = field(default_factory=ProgressBus)

    def __post_init__(self) -> None:
        """初始化默认 SQLite 仓储，同时保留测试替换适配器的注入入口。"""

        # 第一步：创建共享数据库对象；每个仓储会按操作打开短连接，适合后台线程调用。
        if self.database is None:
            self.database = SQLiteDatabase(self.workspace.database_path)

        # 第二步：只为没有显式注入的能力创建默认实现，便于单元测试继续使用内存仓储。
        if self.project_repository is None:
            self.project_repository = SQLiteProjectRepository(self.database)
        if self.task_repository is None:
            self.task_repository = SQLiteTaskRepository(self.database)
        if self.subtitle_repository is None:
            self.subtitle_repository = SQLiteSubtitleRepository(self.database)
        if self.export_record_repository is None:
            self.export_record_repository = SQLiteExportRecordRepository(self.database)
        if self.job_queue is None:
            self.job_queue = PersistentJobQueue(self.database)

        # 第三步：把上次进程异常退出留下的运行中任务改成可恢复状态。
        recover = getattr(self.task_repository, "recover_running_tasks", None)
        if recover is not None:
            recover()
        self.job_queue.recover_running()

    def create_asr_engine(self) -> AsrEngine:
        """按照当前配置装配本地 ASR 适配器。

        这里属于 app 层的依赖装配职责，所以负责把配置对象中的模型名、
        设备和缓存目录翻译成具体适配器构造参数。
        真正的识别细节仍然留在 infrastructure 层。
        """

        asr_settings = self.settings.engine.asr
        return FasterWhisperEngine(
            model_name=asr_settings.model_name,
            device=asr_settings.device,
            compute_type=asr_settings.compute_type,
            model_cache_dir=self.settings.runtime.model_cache_dir,
        )

    def create_task_service(self) -> TaskService:
        """构建已经接通阶段 2 本地识别链路的任务服务。

        当前仓储仍是进程内实现，所以应用重启后不会保留项目状态。
        这个限制会在阶段 5 由 SQLite 仓储替换；用例和 UI 调用接口
        不需要因此改变。
        """

        asr_engine = self.create_asr_engine()
        create_project = CreateProject(
            project_repository=self.project_repository,
            task_repository=self.task_repository,
            event_publisher=self.progress_bus,
            project_workspace=self.workspace,
            fingerprint_calculator=Sha256FileFingerprintCalculator(),
        )
        transcribe_video = TranscribeVideo(
            project_repository=self.project_repository,
            task_repository=self.task_repository,
            subtitle_repository=self.subtitle_repository,
            event_publisher=self.progress_bus,
            media_probe=FFprobeAdapter(self.settings.runtime.ffprobe_path),
            audio_extractor=FFmpegAdapter(self.settings.runtime.ffmpeg_path),
            asr_engine=asr_engine,
            subtitle_formatter=SubtitleFormatter(),
            subtitle_aligner=SubtitleAligner(),
            srt_writer=SrtWriter(),
        )
        translation_settings = self.settings.engine.translation
        translator = OpenAICompatibleTranslator(
            base_url=translation_settings.base_url,
            model=translation_settings.model,
            api_key_env=translation_settings.api_key_env,
            timeout_seconds=translation_settings.timeout_seconds,
            max_retries=translation_settings.max_retries,
            batch_builder=TranslationBatchBuilder(
                max_segments=translation_settings.max_batch_segments,
                max_characters=translation_settings.max_batch_characters,
            ),
        )
        translate_subtitles = TranslateSubtitles(
            project_repository=self.project_repository,
            task_repository=self.task_repository,
            subtitle_repository=self.subtitle_repository,
            translator=translator,
            event_publisher=self.progress_bus,
            subtitle_writer=SrtWriter(),
        )
        export_video = ExportVideo(
            project_repository=self.project_repository,
            task_repository=self.task_repository,
            export_record_repository=self.export_record_repository,
            exporter=CompositeVideoExporter(
                exporters={
                    ExportMode.SOFT_SUBTITLE: SoftSubtitleExporter(),
                    ExportMode.BURN_IN: BurnInExporter(
                        self.settings.runtime.ffmpeg_path
                    ),
                }
            ),
            event_publisher=self.progress_bus,
        )
        return TaskService(
            create_project_usecase=create_project,
            transcribe_video_usecase=transcribe_video,
            translate_subtitles_usecase=translate_subtitles,
            export_video_usecase=export_video,
        )

    def create_main_window(self) -> MainWindow:
        """构建主窗口，并注入它依赖的服务。"""

        from ui.windows.main_window import MainWindow

        # 任务服务在这里创建一次，然后由主窗口和子页面共享。
        # 这样任务相关状态就集中保存在一个对象里，不会在多个控件之间重复拷贝。
        task_service = self.create_task_service()
        return MainWindow(
            settings=self.settings,
            workspace=self.workspace,
            task_service=task_service,
            logger=self.logger,
            progress_bus=self.progress_bus,
        )
