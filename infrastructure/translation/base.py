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
    """翻译服务返回无法解析的内容时抛出的异常。

    参数：
        message：面向用户的错误原因。
        raw_response：可选的大模型原始文本正文，用于帮助用户判断模型究竟
            返回了说明文字、错误 JSON 还是其他不符合协议的内容。

    原始响应只用于本地诊断展示，不会再次发送到外部服务。为避免异常内容
    过长撑坏消息框或任务记录，这里会保留开头并明确标记截断。
    """

    max_response_preview_characters = 4_000

    def __init__(self, message: str, raw_response: str | None = None) -> None:
        """保存错误原因，并把可用的模型原始返回追加到异常文本。"""

        self.message = message
        self.raw_response = raw_response
        if raw_response is None:
            super().__init__(message)
            return

        preview = raw_response.strip() or "<空内容>"
        if len(preview) > self.max_response_preview_characters:
            omitted = len(preview) - self.max_response_preview_characters
            preview = (
                preview[: self.max_response_preview_characters]
                + f"\n……已截断其余 {omitted} 个字符"
            )
        super().__init__(f"{message}\n\n大模型原始返回：\n{preview}")
