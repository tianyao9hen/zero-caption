"""OpenAI 兼容翻译适配器单元测试。

测试通过注入传输函数模拟远程服务，重点保护隐私边界、响应回填和临时失败重试。
"""

from __future__ import annotations

import json
from urllib.error import URLError

import pytest

from core.dto.subtitle_dto import SubtitleSegmentDTO
from infrastructure.translation.batch_builder import TranslationBatchBuilder
from infrastructure.translation.base import (
    TranslationConfigurationError,
    TranslationResponseError,
)
from infrastructure.translation.openai_translator import (
    OpenAICompatibleTranslator,
    TRANSLATION_RESPONSE_CONTRACT,
)


def _segments() -> list[SubtitleSegmentDTO]:
    """构造两条带稳定时间轴的原文字幕。"""

    return [
        SubtitleSegmentDTO("seg-1", 0, 1_000, "こんにちは", "ja-JP"),
        SubtitleSegmentDTO("seg-2", 1_000, 2_000, "世界", "ja-JP"),
    ]


def test_translator_sends_only_text_and_language_context(monkeypatch) -> None:
    """翻译请求不应包含视频路径等媒体信息，并应正确回填时间轴。"""

    # arrange：传输假实现检查适配器送出的结构并返回标准 JSON 对象。
    monkeypatch.setenv("TEST_TRANSLATION_KEY", "secret-value")
    requests: list[tuple[str, dict[str, str], dict[str, object], float]] = []

    def transport(endpoint, headers, payload, timeout):
        requests.append((endpoint, headers, payload, timeout))
        content = json.dumps(
            {
                "translations": [
                    {"id": "seg-1", "text": "你好"},
                    {"id": "seg-2", "text": "世界"},
                ]
            },
            ensure_ascii=False,
        )
        return {"choices": [{"message": {"content": content}}]}

    translator = OpenAICompatibleTranslator(
        base_url="https://translation.example/v1",
        model="test-model",
        api_key_env="TEST_TRANSLATION_KEY",
        system_prompt="自定义字幕系统提示词",
        batch_builder=TranslationBatchBuilder(max_segments=10, max_characters=100),
        transport=transport,
    )

    # act
    result = translator.translate_segments(_segments(), "ja-JP", "zh-CN", "动画对白")

    # assert：检查端点、语言和字幕正文；媒体路径从未进入请求结构。
    assert requests[0][0] == "https://translation.example/v1/chat/completions"
    assert requests[0][1]["Authorization"] == "Bearer secret-value"
    assert requests[0][2]["enable_thinking"] is False
    assert requests[0][2]["response_format"] == {"type": "json_object"}
    assert requests[0][2]["max_tokens"] >= 512
    system_content = requests[0][2]["messages"][0]["content"]  # type: ignore[index]
    assert system_content.startswith("自定义字幕系统提示词")
    assert TRANSLATION_RESPONSE_CONTRACT in system_content
    assert '"translations"' in system_content
    user_content = requests[0][2]["messages"][1]["content"]  # type: ignore[index]
    request_data = json.loads(user_content)
    assert request_data["source_language"] == "ja-JP"
    assert request_data["target_language"] == "zh-CN"
    assert [item["text"] for item in request_data["segments"]] == ["こんにちは", "世界"]
    assert "source_video" not in request_data
    assert [segment.text for segment in result] == ["你好", "世界"]
    assert [(segment.start_ms, segment.end_ms) for segment in result] == [(0, 1_000), (1_000, 2_000)]


def test_translator_accepts_legacy_single_object_response(monkeypatch) -> None:
    """旧提示词诱导模型返回单对象时，单句翻译仍应可靠回填本地字幕编号。"""

    # arrange：这个格式来自旧提示词中“要求数组、示例却是对象”的历史冲突。
    monkeypatch.setenv("TEST_TRANSLATION_KEY", "secret-value")

    def transport(endpoint, headers, payload, timeout):
        return {"choices": [{"message": {"content": '{"text":"你好"}'}}]}

    translator = OpenAICompatibleTranslator(
        base_url="https://translation.example/v1",
        model="test-model",
        api_key_env="TEST_TRANSLATION_KEY",
        transport=transport,
    )

    # act：响应没有 id，但当前批次只有一条字幕，因此可以使用本地稳定编号补齐。
    result = translator.translate_segments([_segments()[0]], "ja-JP", "zh-CN")

    # assert：只兼容响应结构，不采信远程时间轴或其他业务字段。
    assert result[0].segment_id == "seg-1"
    assert result[0].text == "你好"
    assert result[0].start_ms == 0


def test_translator_includes_raw_model_content_in_format_error(monkeypatch) -> None:
    """响应结构错误时，用户应能在异常信息中看到模型实际返回的正文。"""

    # arrange：模拟模型忽略 JSON 协议，直接返回一段自然语言说明。
    monkeypatch.setenv("TEST_TRANSLATION_KEY", "secret-value")
    raw_content = "我已经完成翻译，结果是：你好"

    def transport(endpoint, headers, payload, timeout):
        return {"choices": [{"message": {"content": raw_content}}]}

    translator = OpenAICompatibleTranslator(
        base_url="https://translation.example/v1",
        model="test-model",
        api_key_env="TEST_TRANSLATION_KEY",
        transport=transport,
    )

    # act / assert：既保留稳定错误原因，也附带原始正文供用户自行判断。
    with pytest.raises(TranslationResponseError) as exc_info:
        translator.translate_segments([_segments()[0]], "ja-JP", "zh-CN")

    assert "翻译服务返回内容无法解析。" in str(exc_info.value)
    assert "大模型原始返回：" in str(exc_info.value)
    assert raw_content in str(exc_info.value)


def test_translator_prefers_api_key_configured_in_application(monkeypatch) -> None:
    """软件内填写的密钥应优先于环境变量，并且只进入授权请求头。"""

    # arrange：环境变量故意设置成另一值，用来证明显式用户配置具有更高优先级。
    monkeypatch.setenv("TEST_TRANSLATION_KEY", "environment-secret")
    captured_headers: list[dict[str, str]] = []

    def transport(endpoint, headers, payload, timeout):
        captured_headers.append(headers)
        return {
            "choices": [
                {"message": {"content": json.dumps([{"id": "seg-1", "text": "你好"}])}}
            ]
        }

    translator = OpenAICompatibleTranslator(
        base_url="https://translation.example/v1",
        model="test-model",
        api_key="application-secret",
        api_key_env="TEST_TRANSLATION_KEY",
        transport=transport,
    )

    # act
    translator.translate_segments([_segments()[0]], "ja-JP", "zh-CN")

    # assert：密钥只用于请求头，翻译正文构造仍不包含认证信息。
    assert captured_headers[0]["Authorization"] == "Bearer application-secret"


def test_translator_retries_temporary_network_failure(monkeypatch) -> None:
    """网络临时失败时应按指数退避重试，并在成功后返回译文。"""

    # arrange：前两次模拟网络失败，第三次返回有效响应。
    monkeypatch.setenv("TEST_TRANSLATION_KEY", "secret-value")
    attempts = 0
    sleeps: list[float] = []

    def transport(endpoint, headers, payload, timeout):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise URLError("temporary network failure")
        return {
            "choices": [
                {"message": {"content": json.dumps([{"id": "seg-1", "text": "你好"}])}}
            ]
        }

    translator = OpenAICompatibleTranslator(
        base_url="https://translation.example/v1",
        model="test-model",
        api_key_env="TEST_TRANSLATION_KEY",
        max_retries=2,
        transport=transport,
        sleep=sleeps.append,
    )

    # act
    result = translator.translate_segments([_segments()[0]], "ja-JP", "zh-CN")

    # assert
    assert attempts == 3
    assert sleeps == [1, 2]
    assert result[0].text == "你好"


def test_translator_requires_api_key_only_when_translation_is_needed(monkeypatch) -> None:
    """缺少密钥时应拒绝真实翻译，但同语言请求可以直接复用原文。"""

    # arrange：确保测试环境没有意外继承真实密钥。
    monkeypatch.delenv("MISSING_TRANSLATION_KEY", raising=False)
    translator = OpenAICompatibleTranslator(
        base_url="https://translation.example/v1",
        model="test-model",
        api_key_env="MISSING_TRANSLATION_KEY",
    )

    # act / assert：不同语言需要密钥；相同语言属于无网络的纯数据映射。
    with pytest.raises(TranslationConfigurationError):
        translator.translate_segments([_segments()[0]], "ja-JP", "zh-CN")
    assert translator.translate_segments([_segments()[0]], "ja-JP", "ja-JP")[0].text == "こんにちは"


def test_model_test_uses_current_system_and_user_prompts(monkeypatch) -> None:
    """模型测试应发送当前两类提示词，并原样返回模型文本。"""

    monkeypatch.setenv("TEST_TRANSLATION_KEY", "secret-value")
    requests: list[dict[str, object]] = []

    def transport(endpoint, headers, payload, timeout):
        requests.append(payload)
        return {"choices": [{"message": {"content": "测试成功"}}]}

    translator = OpenAICompatibleTranslator(
        base_url="https://translation.example/v1",
        model="test-model",
        api_key_env="TEST_TRANSLATION_KEY",
        system_prompt="只输出测试结果",
        transport=transport,
    )

    result = translator.test_prompt("请回答连接是否正常")

    assert result == "测试成功"
    assert requests[0]["enable_thinking"] is False
    assert requests[0]["messages"] == [
        {"role": "system", "content": "只输出测试结果"},
        {"role": "user", "content": "请回答连接是否正常"},
    ]
