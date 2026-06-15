"""运行时探针相关集成测试。

这些测试保护阶段0新增的“环境可检查”能力，确保我们可以在真正接入
`FFmpeg`、`faster-whisper` 和翻译接口之前，先判断当前机器是否具备基础条件。
"""

from unittest.mock import patch

from config.settings import Settings
from scripts.check_runtime import probe_runtime


def test_probe_runtime_reports_missing_ffmpeg(tmp_path):
    """缺少 `ffmpeg` 时，探针应把整体结果标记为失败。"""

    # arrange：构造默认配置，并让命令查找始终失败，
    # 这样可以稳定复现“媒体工具未安装”的场景。
    settings = Settings()

    # act：运行探针。
    with patch("scripts.check_runtime.shutil.which", return_value=None):
        report = probe_runtime(settings=settings, workspace_root=tmp_path)

    # assert：缺少 `ffmpeg` 时应是硬失败，而不是仅给警告。
    assert report.status == "fail"
    assert any(item.name == "ffmpeg" and item.status == "fail" for item in report.items)


def test_probe_runtime_reports_missing_translation_config_as_warning(tmp_path):
    """翻译配置不完整时，探针应给出警告而不是直接失败。"""

    # arrange：这里让 `ffmpeg` 和 `ffprobe` 看起来都存在，
    # 只保留翻译配置为空，以验证整体结果会降级成警告。
    settings = Settings()

    # act：运行探针。
    with patch("scripts.check_runtime.shutil.which", side_effect=["ffmpeg", "ffprobe"]):
        with patch("scripts.check_runtime.importlib.util.find_spec", return_value=object()):
            report = probe_runtime(settings=settings, workspace_root=tmp_path)

    # assert：翻译配置尚未补齐时，不该阻断阶段0和阶段2的开发。
    assert report.status == "warn"
    assert any(item.name == "translation_config" and item.status == "warn" for item in report.items)
