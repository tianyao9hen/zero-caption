"""配置加载相关测试。

这些测试用于保护一个对初学者友好的行为：即使用户还没有自己创建配置文件，
应用也应该能正常启动。阶段 1 还会顺手保护导出模式的稳定默认值，
避免配置层和领域枚举层各说各话。
"""

from config.settings import load_settings
from core.domain.enums import ExportMode


def test_load_settings_defaults_when_missing(tmp_path, monkeypatch):
    """配置文件缺失时，应回退到代码中的默认值。"""

    # arrange：把当前工作目录切到一个空的临时目录，
    # 这样默认配置路径就不会存在。
    monkeypatch.chdir(tmp_path)

    # act：在不传显式路径的情况下加载配置。
    settings = load_settings()

    # assert：加载结果应回退到 `Settings` 中定义的默认值。
    assert settings.app_name == "Zero Caption"
    assert str(settings.workspace_root) == "data"
    assert settings.engine.asr.provider == "faster-whisper"
    assert settings.engine.translation.api_key_env == "OPENAI_API_KEY"
    assert settings.runtime.ffmpeg_path == "ffmpeg"
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
api_key_env = "OPENAI_API_KEY"

[engine.export]
default_mode = "soft_subtitle"

[runtime]
ffmpeg_path = "ffmpeg"
ffprobe_path = "ffprobe"
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
    assert settings.runtime.ffmpeg_path == "ffmpeg"
    assert settings.task.max_retries == 2
    assert settings.cache.reuse_transcript is True
    assert settings.engine.export.default_mode is ExportMode.SOFT_SUBTITLE


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
