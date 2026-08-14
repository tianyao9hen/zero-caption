"""翻译基础异常模块。

这个文件属于基础设施层，集中定义翻译配置和远程请求失败时使用的异常。
具体的 OpenAI 兼容请求实现放在同目录的 `openai_translator.py` 中，
避免把 HTTP 细节扩散到核心用例和界面层。
"""

from __future__ import annotations


class TranslationError(RuntimeError):
    """远程翻译请求或响应不符合预期时抛出的基础异常。"""


class TranslationConfigurationError(TranslationError):
    """翻译地址、模型或密钥配置缺失时抛出的异常。"""


class TranslationResponseError(TranslationError):
    """翻译服务返回无法解析的内容时抛出的异常。"""
