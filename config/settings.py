"""应用骨架的配置加载模块。

这个文件属于配置层，负责把 `TOML` 文本解析成应用其他部分可直接使用的
结构化 `dataclass` 对象。这里不处理业务流程，只负责“配置长什么样”和
“如何从磁盘读取配置”。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Any
import tomllib

from config.paths import resource_path, user_data_path
from core.domain.enums import ExportMode


@dataclass(slots=True)
class AsrSettings:
    """描述本地识别引擎的用户选择和发布模型边界。

    `auto` 表示应用根据实际硬件选择安全组合；`bundled_models` 只描述
    软件已经准备好的模型，运行任务时不会临时访问网络下载模型。
    """

    provider: str = "faster-whisper"
    model_name: str = "auto"
    device: str = "auto"
    compute_type: str = "auto"
    bundled_models: tuple[str, ...] = ("small", "medium")
    allow_cpu_fallback: bool = True


@dataclass(slots=True)
class TranslationSettings:
    """描述翻译引擎的配置。

    `api_key` 由用户在设置页填写，并保存到当前 Windows 用户的数据目录。
    `repr=False` 可以避免调试时直接打印配置对象而意外显示密钥正文。
    当用户没有填写密钥时，适配器仍可从 `api_key_env` 指定的环境变量读取。
    """

    provider: str = "openai-compatible"
    base_url: str = ""
    model: str = ""
    api_key: str = field(default="", repr=False)
    api_key_env: str = "OPENAI_API_KEY"
    system_prompt: str = (
        "你是一名专业字幕翻译器。请忠实、自然、简洁地翻译字幕，"
        "保持人物语气和上下文一致，不添加原文没有的信息。"
    )
    timeout_seconds: float = 60.0
    max_retries: int = 2
    max_batch_segments: int = 1
    max_batch_characters: int = 4_000

    def is_configured(self) -> bool:
        """判断当前设置是否具备发起翻译请求的必要参数。

        接口地址、模型名称和密钥缺一不可。密钥既可以由用户在软件内
        保存，也可以通过 `api_key_env` 指向的环境变量提供；这里只返回
        是否就绪，不返回或记录密钥正文。
        """

        api_key = self.api_key.strip()
        if not api_key and self.api_key_env:
            api_key = os.getenv(self.api_key_env, "").strip()
        return bool(self.base_url.strip() and self.model.strip() and api_key)


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
    """描述普通视频流程和高资源阶段各自的并发边界。

    `max_concurrency` 限制同时存在的完整视频后台线程数量；
    `max_heavy_concurrency` 单独限制识别和视频导出等高资源步骤。
    两层限制分开后，等待识别资源的任务仍可让其他任务继续翻译。
    """

    max_concurrency: int = 2
    max_heavy_concurrency: int = 1
    max_retries: int = 2

    def __post_init__(self) -> None:
        """校验并发边界，避免后台线程永久等待无效的零个槽位。"""

        if self.max_concurrency <= 0:
            raise ValueError("视频任务并发数必须大于 0。")
        if self.max_heavy_concurrency <= 0:
            raise ValueError("高资源任务并发数必须大于 0。")
        if self.max_heavy_concurrency > self.max_concurrency:
            raise ValueError("高资源任务并发数不能超过视频任务并发数。")
        if self.max_retries < 0:
            raise ValueError("任务最大重试次数不能小于 0。")


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


def load_settings(
    path: str | Path | None = None,
    *,
    user_path: str | Path | None = None,
) -> Settings:
    """从 `TOML` 文件中加载配置。

    参数：
        path：可选的单一配置文件路径。显式传入时只读取该文件，
            主要供测试、脚本或专用配置使用。
        user_path：可选的用户配置路径。未传 `path` 时，应用会先读取
            随程序发布的默认配置，再用这个用户配置覆盖同名字段。

    返回：
        一个 `Settings` 实例。任何配置文件不存在时都会回退到
        `dataclass` 或随程序发布的默认值，保证首次启动仍可运行。
    """

    # 显式路径表示调用方希望独立读取一个配置文件，不再混入本机用户设置。
    # 正常启动时则先读只读默认值，再叠加位于用户目录的可写配置。
    if path is not None:
        data = _load_toml(Path(path))
    else:
        default_data = _load_toml(resource_path("config/default.toml"))
        user_config_path = (
            Path(user_path) if user_path is not None else user_data_path("settings.toml")
        )
        data = _merge_mappings(default_data, _load_toml(user_config_path))

    return _settings_from_data(data)


def save_translation_settings(
    settings: TranslationSettings,
    path: str | Path | None = None,
) -> Path:
    """兼容旧调用方，只更新本地 `TOML` 中的大模型翻译设置。

    参数：
        settings：设置页收集到的翻译配置。
        path：可选的输出路径。应用运行时默认写入当前用户的数据目录；
            测试可以传入临时路径，避免修改真实用户配置。

    返回：
        实际写入的配置文件路径。

    副作用：
        会保留已有的 ASR 选择，并通过统一引擎设置入口原子替换配置文件。
    """

    target = Path(path) if path is not None else user_data_path("settings.toml")

    # 兼容旧调用方时先读取已有识别选择，再只替换翻译分组。
    # 这样旧接口不会意外清除用户刚保存的 GPU 和模型设置。
    current = load_settings(user_path=target)
    return save_engine_settings(
        EngineSettings(
            asr=current.engine.asr,
            translation=settings,
            export=current.engine.export,
        ),
        target,
    )


def save_engine_settings(
    settings: EngineSettings,
    path: str | Path | None = None,
) -> Path:
    """持久化用户可编辑的本地识别和大模型翻译设置。

    参数：
        settings：设置页提交的完整引擎配置。
        path：可选输出路径；生产环境默认使用当前用户配置文件。

    返回：
        实际写入的 `TOML` 文件路径。

    副作用：
        会原子替换用户配置文件。发布模型清单仍以随包默认配置为准，
        用户只能选择已经内置的模型，不能通过界面注入任意下载地址。
    """

    target = Path(path) if path is not None else user_data_path("settings.toml")

    # 引擎设置和工作区共用同一个用户配置文件。保存其中一组时先读取另一组，
    # 避免用户稍后修改识别参数时把已经选择的工作区路径意外覆盖掉。
    current = load_settings(user_path=target)
    return _save_user_settings(
        current.workspace_root,
        settings,
        current.runtime.model_cache_dir,
        target,
    )


def save_workspace_settings(
    workspace_root: str | Path,
    path: str | Path | None = None,
    *,
    model_cache_dir: str | Path | None = None,
) -> Path:
    """持久化用户选择的工作区，同时保留现有引擎设置。

    参数：
        workspace_root：后续项目、缓存、日志和数据库使用的目录。
        path：可选输出路径；生产环境默认使用当前用户配置文件。
        model_cache_dir：可选的新模型缓存目录；不传时保留当前配置。

    返回：
        实际写入的 `TOML` 文件路径。

    副作用：
        会原子替换用户配置文件，但不会迁移或删除旧工作区内容。
    """

    target = Path(path) if path is not None else user_data_path("settings.toml")
    current = load_settings(user_path=target)
    effective_model_cache = (
        current.runtime.model_cache_dir
        if model_cache_dir is None
        else Path(model_cache_dir)
    )
    return _save_user_settings(
        Path(workspace_root),
        current.engine,
        effective_model_cache,
        target,
    )


def _save_user_settings(
    workspace_root: Path,
    engine_settings: EngineSettings,
    model_cache_dir: Path,
    target: Path,
) -> Path:
    """把当前可编辑设置一次性写入用户配置文件。"""

    _validate_asr_settings(engine_settings.asr)
    _validate_translation_settings(engine_settings.translation)
    target.parent.mkdir(parents=True, exist_ok=True)

    asr = engine_settings.asr
    translation = engine_settings.translation
    content = "\n".join(
        [
            "[app]",
            f"workspace_root = {_toml_string(str(workspace_root))}",
            "",
            "[engine.asr]",
            f"provider = {_toml_string(asr.provider)}",
            f"model_name = {_toml_string(asr.model_name)}",
            f"device = {_toml_string(asr.device)}",
            f"compute_type = {_toml_string(asr.compute_type)}",
            f"allow_cpu_fallback = {str(asr.allow_cpu_fallback).lower()}",
            "",
            "[engine.translation]",
            f"provider = {_toml_string(translation.provider)}",
            f"base_url = {_toml_string(translation.base_url)}",
            f"model = {_toml_string(translation.model)}",
            f"api_key = {_toml_string(translation.api_key)}",
            f"api_key_env = {_toml_string(translation.api_key_env)}",
            f"system_prompt = {_toml_string(translation.system_prompt)}",
            f"timeout_seconds = {translation.timeout_seconds}",
            f"max_retries = {translation.max_retries}",
            f"max_batch_segments = {translation.max_batch_segments}",
            f"max_batch_characters = {translation.max_batch_characters}",
            "",
            "[runtime]",
            f"model_cache_dir = {_toml_string(str(model_cache_dir))}",
            "",
        ]
    )
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(target)
    return target


def _settings_from_data(data: dict[str, Any]) -> Settings:
    """把已经合并好的配置字典转换成结构化设置对象。"""

    settings = Settings()

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

    # 卸载软件时用户可以选择保留本机设置，重装后就可能继续读到旧版本写入的
    # 空提示词。空白内容无法执行翻译，也不应覆盖新版随包提供的可用默认值；
    # 非空内容仍原样保留，因此用户在设置页编辑的自定义提示词不会丢失。
    system_prompt = translation.get(
        "system_prompt",
        settings.engine.translation.system_prompt,
    )
    if not isinstance(system_prompt, str) or not system_prompt.strip():
        system_prompt = settings.engine.translation.system_prompt

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
                bundled_models=tuple(
                    asr.get(
                        "bundled_models",
                        settings.engine.asr.bundled_models,
                    )
                ),
                allow_cpu_fallback=bool(
                    asr.get(
                        "allow_cpu_fallback",
                        settings.engine.asr.allow_cpu_fallback,
                    )
                ),
            ),
            translation=TranslationSettings(
                provider=translation.get("provider", settings.engine.translation.provider),
                base_url=translation.get("base_url", settings.engine.translation.base_url),
                model=translation.get("model", settings.engine.translation.model),
                api_key=translation.get("api_key", settings.engine.translation.api_key),
                api_key_env=translation.get("api_key_env", settings.engine.translation.api_key_env),
                system_prompt=system_prompt,
                timeout_seconds=float(
                    translation.get(
                        "timeout_seconds",
                        settings.engine.translation.timeout_seconds,
                    )
                ),
                max_retries=int(
                    translation.get(
                        "max_retries",
                        settings.engine.translation.max_retries,
                    )
                ),
                max_batch_segments=int(
                    translation.get(
                        "max_batch_segments",
                        settings.engine.translation.max_batch_segments,
                    )
                ),
                max_batch_characters=int(
                    translation.get(
                        "max_batch_characters",
                        settings.engine.translation.max_batch_characters,
                    )
                ),
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
            max_concurrency=int(
                task.get("max_concurrency", settings.task.max_concurrency)
            ),
            max_heavy_concurrency=int(
                task.get(
                    "max_heavy_concurrency",
                    settings.task.max_heavy_concurrency,
                )
            ),
            max_retries=int(task.get("max_retries", settings.task.max_retries)),
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


def _load_toml(path: Path) -> dict[str, Any]:
    """读取一个可选的 `TOML` 文件，不存在时返回空字典。"""

    if not path.exists():
        return {}
    # `tomllib` 读取 `TOML` 时需要二进制模式，这是标准库接口的要求。
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _merge_mappings(
    base: dict[str, Any],
    override: dict[str, Any],
) -> dict[str, Any]:
    """递归合并配置分组，让用户文件只覆盖自己显式填写的字段。"""

    result = dict(base)
    for key, value in override.items():
        current = result.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            result[key] = _merge_mappings(current, value)
        else:
            result[key] = value
    return result


def _validate_translation_settings(settings: TranslationSettings) -> None:
    """检查设置页无法完全表达的数值边界，避免保存无效配置。"""

    if not settings.system_prompt.strip():
        raise ValueError("翻译系统提示词不能为空。")
    if settings.timeout_seconds <= 0:
        raise ValueError("翻译请求超时时间必须大于 0。")
    if settings.max_retries < 0:
        raise ValueError("翻译最大重试次数不能小于 0。")
    if settings.max_batch_segments <= 0:
        raise ValueError("单批字幕条数必须大于 0。")
    if settings.max_batch_characters <= 0:
        raise ValueError("单批字幕字符数必须大于 0。")


def _validate_asr_settings(settings: AsrSettings) -> None:
    """验证识别设置只引用软件支持并已准备的选项。"""

    if not settings.bundled_models:
        raise ValueError("至少需要准备一个本地识别模型。")
    if settings.model_name not in {"auto", *settings.bundled_models}:
        raise ValueError("识别模型必须选择自动或软件已内置的模型。")
    if settings.device not in {"auto", "cpu", "cuda"}:
        raise ValueError("识别设备必须是自动、CPU 或 CUDA。")
    if settings.compute_type not in {
        "auto",
        "int8",
        "float16",
        "int8_float16",
    }:
        raise ValueError("识别精度不是软件支持的选项。")


def _toml_string(value: str) -> str:
    """把字符串编码成兼容 `TOML` 基础字符串的安全文本。"""

    # JSON 与 TOML 的双引号字符串共享这里需要的转义规则，
    # 用标准库编码可以正确处理引号、反斜杠和中文文本。
    return json.dumps(str(value), ensure_ascii=False)


def _load_export_mode(value: object) -> ExportMode:
    """把配置文件里的导出模式转换成稳定枚举。"""

    if isinstance(value, ExportMode):
        return value
    try:
        return ExportMode(str(value))
    except ValueError:
        return ExportMode.SOFT_SUBTITLE
