"""应用骨架的配置加载模块。

这个文件属于配置层，负责把 `TOML` 文本解析成应用其他部分可直接使用的
结构化 `dataclass` 对象。这里不处理业务流程，只负责“配置长什么样”和
“如何从磁盘读取配置”。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import tomllib

from core.domain.enums import ExportMode


@dataclass(slots=True)
class AsrSettings:
    """描述本地识别引擎的配置。"""

    provider: str = "faster-whisper"
    model_name: str = "small"
    device: str = "cpu"
    compute_type: str = "int8"


@dataclass(slots=True)
class TranslationSettings:
    """描述翻译引擎的配置。

    这里暂时只表达阶段0到阶段3会用到的最小字段：
    翻译提供方、接口地址、模型名，以及保存密钥名的环境变量键。
    """

    provider: str = "openai-compatible"
    base_url: str = ""
    model: str = ""
    api_key_env: str = "OPENAI_API_KEY"


@dataclass(slots=True)
class ExportSettings:
    """描述导出阶段的默认模式配置。"""

    default_mode: ExportMode = ExportMode.SOFT_SUBTITLE


@dataclass(slots=True)
class EngineSettings:
    """把多个可替换引擎配置组织到一个总对象里。

    这样后续代码读取配置时可以沿着 `settings.engine.asr` 这类路径访问，
    比继续往顶层堆很多字符串字段更容易维护。
    """

    asr: AsrSettings = field(default_factory=AsrSettings)
    translation: TranslationSettings = field(default_factory=TranslationSettings)
    export: ExportSettings = field(default_factory=ExportSettings)


@dataclass(slots=True)
class RuntimeSettings:
    """描述运行时依赖和本地缓存路径。"""

    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    model_cache_dir: Path = Path("data/models")


@dataclass(slots=True)
class TaskSettings:
    """描述后台任务执行的最小控制参数。"""

    max_concurrency: int = 1
    max_retries: int = 2


@dataclass(slots=True)
class SubtitleSettings:
    """描述字幕处理链路的默认语言参数。"""

    source_language: str = "auto"
    target_language: str = "zh-CN"


@dataclass(slots=True)
class CacheSettings:
    """描述阶段0先需要表达的缓存策略。"""

    enabled: bool = True
    reuse_audio: bool = True
    reuse_transcript: bool = True


@dataclass(slots=True)
class Settings:
    """保存应用运行时使用的结构化配置。

    顶层字段仍保留启动骨架已经依赖的应用级配置。
    新增的子配置对象用于承载后续 MVP 主链路需要的运行时信息。
    """

    app_name: str = "Zero Caption"
    workspace_root: Path = Path("data")
    log_level: str = "INFO"
    language: str = "zh-CN"
    theme: str = "system"
    default_page: str = "projects"
    engine: EngineSettings = field(default_factory=EngineSettings)
    runtime: RuntimeSettings = field(default_factory=RuntimeSettings)
    task: TaskSettings = field(default_factory=TaskSettings)
    subtitle: SubtitleSettings = field(default_factory=SubtitleSettings)
    cache: CacheSettings = field(default_factory=CacheSettings)


def load_settings(path: str | Path | None = None) -> Settings:
    """从 `TOML` 文件中加载配置。

    参数：
        path：可选的配置文件路径。不传时，默认使用仓库中的
            `config/default.toml`。

    返回：
        一个 `Settings` 实例。如果文件不存在，就返回 dataclass 的默认值，
        让应用仍然可以正常启动。
    """

    settings = Settings()

    # `Path` 比手工拼接字符串更适合处理路径，也方便后续统一转换成路径对象。
    config_path = Path(path) if path else Path("config/default.toml")
    if not config_path.exists():
        return settings

    # `tomllib` 读取 `TOML` 时需要二进制模式。
    with config_path.open("rb") as handle:
        data = tomllib.load(handle)

    # 第一步：读取顶层分组。
    # 这里用空字典兜底，是为了在配置文件只写局部字段时仍然能安全回退默认值。
    app = data.get("app", {})
    ui = data.get("ui", {})
    engine = data.get("engine", {})
    runtime = data.get("runtime", {})
    task = data.get("task", {})
    subtitle = data.get("subtitle", {})
    cache = data.get("cache", {})

    # 第二步：把引擎相关的嵌套分组拆开。
    # 这样每个子配置对象都只关心自己负责的字段，不需要解析整棵配置树。
    asr = engine.get("asr", {})
    translation = engine.get("translation", {})
    export = engine.get("export", {})

    # 第三步：组装结构化 `Settings`。
    # 这里刻意显式写出每个字段，而不是偷懒直接把字典展开，
    # 是为了让字段默认值、类型转换和配置名保持清晰可见。
    return Settings(
        app_name=app.get("name", settings.app_name),
        workspace_root=Path(app.get("workspace_root", str(settings.workspace_root))),
        log_level=app.get("log_level", settings.log_level),
        language=app.get("language", settings.language),
        theme=app.get("theme", settings.theme),
        default_page=ui.get("default_page", settings.default_page),
        engine=EngineSettings(
            asr=AsrSettings(
                provider=asr.get("provider", settings.engine.asr.provider),
                model_name=asr.get("model_name", settings.engine.asr.model_name),
                device=asr.get("device", settings.engine.asr.device),
                compute_type=asr.get("compute_type", settings.engine.asr.compute_type),
            ),
            translation=TranslationSettings(
                provider=translation.get("provider", settings.engine.translation.provider),
                base_url=translation.get("base_url", settings.engine.translation.base_url),
                model=translation.get("model", settings.engine.translation.model),
                api_key_env=translation.get("api_key_env", settings.engine.translation.api_key_env),
            ),
            export=ExportSettings(
                default_mode=_load_export_mode(
                    export.get("default_mode", settings.engine.export.default_mode)
                ),
            ),
        ),
        runtime=RuntimeSettings(
            ffmpeg_path=runtime.get("ffmpeg_path", settings.runtime.ffmpeg_path),
            ffprobe_path=runtime.get("ffprobe_path", settings.runtime.ffprobe_path),
            model_cache_dir=Path(runtime.get("model_cache_dir", str(settings.runtime.model_cache_dir))),
        ),
        task=TaskSettings(
            max_concurrency=task.get("max_concurrency", settings.task.max_concurrency),
            max_retries=task.get("max_retries", settings.task.max_retries),
        ),
        subtitle=SubtitleSettings(
            source_language=subtitle.get("source_language", settings.subtitle.source_language),
            target_language=subtitle.get("target_language", settings.subtitle.target_language),
        ),
        cache=CacheSettings(
            enabled=cache.get("enabled", settings.cache.enabled),
            reuse_audio=cache.get("reuse_audio", settings.cache.reuse_audio),
            reuse_transcript=cache.get("reuse_transcript", settings.cache.reuse_transcript),
        ),
    )


def _load_export_mode(value: object) -> ExportMode:
    """把配置文件里的导出模式转换成稳定枚举。"""

    if isinstance(value, ExportMode):
        return value
    try:
        return ExportMode(str(value))
    except ValueError:
        return ExportMode.SOFT_SUBTITLE
