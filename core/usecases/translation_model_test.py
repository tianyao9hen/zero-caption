"""大模型翻译配置测试用例。

这个模块属于核心层，只负责校验测试输入并调用抽象端口。
网络请求、认证和响应解析仍由基础设施适配器完成。
"""

from __future__ import annotations

from dataclasses import dataclass

from core.ports.translator import TranslationModelTester


@dataclass(slots=True)
class TranslationModelTest:
    """用用户输入的提示词验证当前大模型和系统提示词。"""

    tester: TranslationModelTester

    def execute(self, user_prompt: str) -> str:
        """执行一次纯文本模型测试并返回模型正文。

        参数：
            user_prompt：用户在设置页输入的测试提示词。

        返回：
            大模型返回的文本内容。

        副作用：
            会通过端口访问外部大模型服务，但不会读写媒体文件。
        """

        prompt = user_prompt.strip()
        if not prompt:
            raise ValueError("请输入用于测试模型的用户提示词。")
        return self.tester.test_prompt(prompt)
