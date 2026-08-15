"""配置加载相关测试。

这些测试用于保护一个对初学者友好的行为：即使用户还没有自己创建配置文件，
应用也应该能正常启动。阶段 1 还会顺手保护导出模式的稳定默认值，
避免配置层和领域枚举层各说各话。
"""

from config.settings import (
    AsrSettings,
    EngineSettings,
    TranslationSettings,
    load_settings,
    save_engine_settings,
    save_translation_settings,
)
from core.domain.enums import ExportMode


def test_load_settings_defaults_when_missing(tmp_path, monkeypatch):
    """用户配置缺失时，应继续使用随程序发布的默认配置。"""

    # arrange：当前工作目录不再参与默认配置解析，仍切换到临时目录，
    # 用来保护打包程序从任意目录启动时都能找到内置配置。
    monkeypatch.chdir(tmp_path)

    # act：指定一个不存在的用户配置文件，模拟首次启动。
    settings = load_settings(user_path=tmp_path / "missing-user-settings.toml")

    # assert：应用信息来自内置配置，媒体工具也指向随包资源路径。
    assert settings.app_name == "Zero Caption"
    assert str(settings.workspace_root) == "data"
    assert settings.engine.asr.provider == "faster-whisper"
    assert settings.engine.asr.model_name == "auto"
    assert settings.engine.asr.device == "auto"
    assert settings.engine.asr.bundled_models == ("small", "medium")
    assert settings.engine.translation.api_key_env == "OPENAI_API_KEY"
    assert settings.engine.translation.api_key == ""
    assert settings.runtime.ffmpeg_path == "resources/bin/ffmpeg/ffmpeg.exe"
    assert settings.task.max_concurrency == 1
    assert settings.cache.enabled is True
    assert settings.engine.export.default_mode is ExportMode.SOFT_SUBTITLE


def test_load_settings_reads_runtime_sections(tmp_path):
    """配置文件存在时，应能读取阶段0新增的运行时配置分组。"""

    # arrange：写入一个包含阶段0新增分组的配置文件，
    # 用来保护后续 `Settings` 结构化扩展不会回退成扁平字符串字段。
    config_file = tmp_path / "custom.toml"
    config_file.write_text(
        """
[app]
name = "Zero Caption"
workspace_root = "data"
log_level = "INFO"
language = "zh-CN"
theme = "system"

[ui]
default_page = "projects"

[engine.asr]
provider = "faster-whisper"
model_name = "small"
device = "cpu"
compute_type = "int8"

[engine.translation]
provider = "openai-compatible"
base_url = "https://example.invalid/v1"
model = "gpt-4o-mini"
api_key = "test-key"
api_key_env = "OPENAI_API_KEY"
timeout_seconds = 30.0
max_retries = 3
max_batch_segments = 10
max_batch_characters = 2000

[engine.export]
default_mode = "soft_subtitle"

[runtime]
ffmpeg_path = "resources/bin/ffmpeg/ffmpeg.exe"
ffprobe_path = "resources/bin/ffmpeg/ffprobe.exe"
model_cache_dir = "data/models"

[task]
max_concurrency = 1
max_retries = 2

[subtitle]
source_language = "auto"
target_language = "zh-CN"

[cache]
enabled = true
reuse_audio = true
reuse_transcript = true
""",
        encoding="utf-8",
    )

    # act：显式读取这个配置文件。
    settings = load_settings(config_file)

    # assert：当前实现需要把导出模式解析成稳定枚举，
    # 避免后续在代码里继续到处散落字符串字面量。
    assert settings.engine.asr.provider == "faster-whisper"
    assert settings.engine.translation.provider == "openai-compatible"
    assert settings.engine.translation.api_key == "test-key"
    assert settings.engine.translation.timeout_seconds == 30.0
    assert settings.engine.translation.max_retries == 3
    assert settings.engine.translation.max_batch_segments == 10
    assert settings.engine.translation.max_batch_characters == 2000
    assert settings.runtime.ffmpeg_path == "resources/bin/ffmpeg/ffmpeg.exe"
    assert settings.task.max_retries == 2
    assert settings.cache.reuse_transcript is True
    assert settings.engine.export.default_mode is ExportMode.SOFT_SUBTITLE


def test_load_settings_merges_user_translation_with_bundled_defaults(tmp_path):
    """用户配置只写翻译分组时，不应丢失内置的媒体和识别设置。"""

    # arrange：真实设置页目前只写入这个分组，测试保护递归覆盖行为。
    user_file = tmp_path / "settings.toml"
    user_file.write_text(
        """
[engine.translation]
base_url = "https://llm.example/v1"
model = "caption-model"
api_key = "local-secret"
""",
        encoding="utf-8",
    )

    # act
    settings = load_settings(user_path=user_file)

    # assert：用户字段生效，未覆盖字段继续沿用随包默认值。
    assert settings.engine.translation.base_url == "https://llm.example/v1"
    assert settings.engine.translation.model == "caption-model"
    assert settings.engine.translation.api_key == "local-secret"
    assert settings.engine.translation.max_retries == 2
    assert settings.engine.asr.model_name == "auto"
    assert settings.runtime.ffmpeg_path == "resources/bin/ffmpeg/ffmpeg.exe"


def test_save_translation_settings_round_trip_and_masks_repr(tmp_path):
    """设置页保存的翻译参数应可重新加载，配置对象表示不应泄露密钥。"""

    # arrange：使用包含引号的地址，顺便保护 `TOML` 字符串转义逻辑。
    translation = TranslationSettings(
        base_url='https://llm.example/v1?profile="caption"',
        model="caption-pro",
        api_key="very-secret-key",
        timeout_seconds=45.0,
        max_retries=4,
        max_batch_segments=30,
        max_batch_characters=6_000,
    )
    target = tmp_path / "user" / "settings.toml"

    # act
    saved_path = save_translation_settings(translation, target)
    reloaded = load_settings(user_path=target).engine.translation

    # assert：所有用户可编辑字段都应完整往返，调试表示中不出现密钥正文。
    assert saved_path == target
    assert reloaded.base_url == translation.base_url
    assert reloaded.model == "caption-pro"
    assert reloaded.api_key == "very-secret-key"
    assert reloaded.timeout_seconds == 45.0
    assert reloaded.max_retries == 4
    assert reloaded.max_batch_segments == 30
    assert reloaded.max_batch_characters == 6_000
    assert "very-secret-key" not in repr(translation)


def test_load_settings_exposes_nested_config_objects(tmp_path):
    """只配置 ASR 分组时，也应能暴露结构化子配置对象。"""

    # arrange：这里故意只写一个最小分组，
    # 用来保护局部配置覆盖时不会破坏其他默认配置。
    config_file = tmp_path / "settings.toml"
    config_file.write_text(
        """
[engine.asr]
provider = "faster-whisper"
model_name = "medium"
device = "cuda"
compute_type = "float16"
""",
        encoding="utf-8",
    )

    # act：加载只覆盖一小部分字段的配置文件。
    settings = load_settings(config_file)

    # assert：`Settings` 应提供结构化子配置对象，
    # 同时允许局部字段覆盖默认值。
    assert settings.engine.asr.model_name == "medium"
    assert settings.engine.asr.device == "cuda"
    assert settings.engine.export.default_mode is ExportMode.SOFT_SUBTITLE


def test_translation_settings_reports_whether_required_values_exist(monkeypatch):
    """翻译就绪判断应同时支持软件内密钥和环境变量密钥。"""

    # arrange：先清空测试环境变量，模拟首次启动且尚未配置大模型。
    monkeypatch.delenv("TEST_CAPTION_API_KEY", raising=False)
    missing = TranslationSettings(api_key_env="TEST_CAPTION_API_KEY")
    configured_in_app = TranslationSettings(
        base_url="https://llm.example/v1",
        model="caption-model",
        api_key="local-secret",
        api_key_env="TEST_CAPTION_API_KEY",
    )
    configured_in_environment = TranslationSettings(
        base_url="https://llm.example/v1",
        model="caption-model",
        api_key_env="TEST_CAPTION_API_KEY",
    )

    # act / assert：缺少参数时返回假，任一安全密钥来源就绪时返回真。
    assert missing.is_configured() is False
    assert configured_in_app.is_configured() is True
    monkeypatch.setenv("TEST_CAPTION_API_KEY", "environment-secret")
    assert configured_in_environment.is_configured() is True


def test_save_engine_settings_round_trips_asr_and_translation(tmp_path) -> None:
    """设置页保存后，本地识别选择和大模型配置都应完整保留。"""

    # arrange：模型清单属于随包配置，不写入用户文件；加载时应继续从默认值补齐。
    engine = EngineSettings(
        asr=AsrSettings(
            model_name="medium",
            device="cuda",
            compute_type="float16",
            allow_cpu_fallback=True,
        ),
        translation=TranslationSettings(
            base_url="https://llm.example/v1",
            model="caption-model",
            api_key="secret",
        ),
    )
    target = tmp_path / "settings.toml"

    # act
    save_engine_settings(engine, target)
    reloaded = load_settings(user_path=target).engine

    # assert
    assert reloaded.asr.model_name == "medium"
    assert reloaded.asr.device == "cuda"
    assert reloaded.asr.compute_type == "float16"
    assert reloaded.asr.allow_cpu_fallback is True
    assert reloaded.asr.bundled_models == ("small", "medium")
    assert reloaded.translation.model == "caption-model"
    assert reloaded.translation.api_key == "secret"
