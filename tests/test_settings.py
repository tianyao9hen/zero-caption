"""配置加载相关测试。

这些测试用于保护一个对初学者友好的行为：即使用户还没有自己创建配置文件，
应用也应该能正常启动。
"""

from config.settings import load_settings


def test_load_settings_defaults_when_missing(tmp_path, monkeypatch):
    """配置文件缺失时，应回退到代码中的默认值。"""

    # 准备：把当前工作目录切到一个空的临时目录，
    # 这样默认配置路径就不会存在。
    monkeypatch.chdir(tmp_path)

    # 执行：在不传显式路径的情况下加载配置。
    settings = load_settings()

    # 断言：加载结果应该退回到 Settings 中定义的默认值。
    assert settings.app_name == "Zero Caption"
    assert str(settings.workspace_root) == "data"
