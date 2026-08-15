"""桌面应用骨架的简单依赖容器。

容器属于 app 层，负责把具体实现装配起来再交给 UI 使用。
这样页面类就不需要自己直接创建基础设施对象。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from config.paths import resource_path
from config.settings import (
    AsrSettings,
    EngineSettings,
    Settings,
    TranslationSettings,
    save_engine_settings,
)
from core.dto.asr_dto import AsrHardwareInfoDTO
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
from core.usecases.translation_model_test import TranslationModelTest
from core.usecases.translate_subtitles import TranslateSubtitles
from infrastructure.asr import CTranslate2HardwareProbe, FasterWhisperEngine
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
    asr_hardware_info: AsrHardwareInfoDTO | None = None

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

        # 第三步：硬件探测只读取驱动能力，不加载 Whisper 模型。
        # 结果作为只读 DTO 缓存，设置页和任务装配共享同一个结论。
        if self.asr_hardware_info is None:
            self.asr_hardware_info = CTranslate2HardwareProbe().probe()

        # 第四步：把上次进程异常退出留下的运行中任务改成可恢复状态。
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
        hardware_info = self._require_asr_hardware_info()
        model_name, device, compute_type = self._resolve_asr_runtime(
            asr_settings,
            hardware_info,
        )
        fallback_model_name = (
            "small" if asr_settings.model_name == "auto" else model_name
        )
        return FasterWhisperEngine(
            model_name=self._resolve_asr_model(model_name, asr_settings),
            device=device,
            compute_type=compute_type,
            model_cache_dir=self.settings.runtime.model_cache_dir,
            allow_cpu_fallback=asr_settings.allow_cpu_fallback,
            fallback_model_name=self._resolve_asr_model(
                fallback_model_name,
                asr_settings,
            ),
            fallback_compute_type="int8",
        )

    def _resolve_asr_model(
        self,
        model_name: str,
        settings: AsrSettings,
    ) -> str:
        """解析本地模型目录，并禁止任务运行时临时下载发布模型。"""

        configured = Path(model_name)
        if configured.is_absolute() and configured.is_dir():
            return str(configured)

        bundled = resource_path(Path("resources/models") / model_name)
        required_files = ("config.json", "model.bin", "tokenizer.json")
        if bundled.is_dir() and all((bundled / name).is_file() for name in required_files):
            return str(bundled)
        if model_name in settings.bundled_models:
            raise RuntimeError(
                f"软件内置识别模型不完整：{model_name}。请重新安装完整版本。"
            )
        raise ValueError(f"未支持的本地识别模型：{model_name}")

    def _resolve_asr_runtime(
        self,
        settings: AsrSettings,
        hardware_info: AsrHardwareInfoDTO,
    ) -> tuple[str, str, str]:
        """把用户的自动选项解析成一次任务实际使用的稳定参数。"""

        model_name = (
            hardware_info.recommended_model
            if settings.model_name == "auto"
            else settings.model_name
        )
        device = (
            hardware_info.recommended_device
            if settings.device == "auto"
            else settings.device
        )
        if settings.compute_type == "auto":
            compute_type = (
                hardware_info.recommended_compute_type
                if device == "cuda"
                else "int8"
            )
        else:
            compute_type = settings.compute_type

        # CPU 不支持 `float16` 和 `int8_float16`。这里做最后一道安全规整，
        # 防止用户手工修改 TOML 后让任务在模型加载前直接失败。
        if device == "cpu" and compute_type in {"float16", "int8_float16"}:
            compute_type = "int8"
        return model_name, device, compute_type

    def _require_asr_hardware_info(self) -> AsrHardwareInfoDTO:
        """返回启动期缓存的硬件快照。"""

        if self.asr_hardware_info is None:
            raise RuntimeError("ASR 硬件能力尚未完成探测。")
        return self.asr_hardware_info

    def create_task_service(self) -> TaskService:
        """构建已经接通导入、识别、逐句翻译和导出的任务服务。

        仓储、进度总线和外部适配器都由容器统一注入。页面只持有最终服务，
        不会直接创建数据库连接、识别模型或翻译客户端。
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
        translator = self._create_translation_adapter(translation_settings)
        translate_subtitles = TranslateSubtitles(
            project_repository=self.project_repository,
            task_repository=self.task_repository,
            subtitle_repository=self.subtitle_repository,
            translator=translator,
            event_publisher=self.progress_bus,
            translation_event_publisher=self.progress_bus,
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
            project_repository=self.project_repository,
        )

    def _create_translation_adapter(
        self,
        settings: TranslationSettings,
    ) -> OpenAICompatibleTranslator:
        """根据一份翻译配置快照创建 OpenAI 兼容适配器。"""

        if settings.provider != "openai-compatible":
            raise ValueError(f"暂不支持的翻译接口类型：{settings.provider}")
        return OpenAICompatibleTranslator(
            base_url=settings.base_url,
            model=settings.model,
            api_key=settings.api_key,
            api_key_env=settings.api_key_env,
            system_prompt=settings.system_prompt,
            timeout_seconds=settings.timeout_seconds,
            max_retries=settings.max_retries,
            batch_builder=TranslationBatchBuilder(
                max_segments=1,
                max_characters=settings.max_batch_characters,
            ),
        )

    def test_translation_model(
        self,
        settings: TranslationSettings,
        user_prompt: str,
    ) -> str:
        """用当前表单快照执行一次纯文本模型测试。

        该方法会由 Qt 工作线程调用。每次都新建适配器，确保用户尚未保存的
        接口、模型、密钥和系统提示词也能参与测试，且不会修改正式任务配置。
        """

        usecase = TranslationModelTest(self._create_translation_adapter(settings))
        return usecase.execute(user_prompt)

    def update_engine_settings(
        self,
        engine_settings: EngineSettings,
    ) -> Settings:
        """持久化识别与大模型配置，并更新后续任务使用的设置对象。

        这个方法位于 `app` 层，因为它需要协调配置层写入和容器状态更新。
        UI 只把用户输入交到这里，不直接探测显卡或创建引擎。
        """

        # 第一步：先完成磁盘写入。写入失败时保持当前运行配置不变，
        # 让界面可以明确反馈失败，而不会出现内存与磁盘配置不一致。
        save_engine_settings(engine_settings)

        # 第二步：`dataclasses.replace` 会基于不可变思路创建新配置对象，
        # 避免多个页面共享同一对象时被原地修改而难以追踪。
        self.settings = replace(
            self.settings,
            engine=engine_settings,
        )
        return self.settings

    def update_translation_settings(
        self,
        translation_settings: TranslationSettings,
    ) -> Settings:
        """兼容旧调用方，只替换翻译配置并走统一持久化入口。"""

        return self.update_engine_settings(
            replace(
                self.settings.engine,
                translation=translation_settings,
            )
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
            task_service_factory=self.create_task_service,
            settings_updater=self.update_engine_settings,
            translation_model_tester=self.test_translation_model,
            asr_hardware_info=self._require_asr_hardware_info(),
            logger=self.logger,
            progress_bus=self.progress_bus,
        )
