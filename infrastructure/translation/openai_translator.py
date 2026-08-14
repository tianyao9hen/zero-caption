"""OpenAI 兼容字幕翻译适配器。

这个适配器只接受字幕片段、语言和可选上下文，不接受视频、音频或项目目录。
网络请求集中在基础设施层，核心层只看到 `Translator` 端口定义的结构化结果。
"""

from __future__ import annotations

import json
import os
import time
from typing import Callable
from urllib import error as urllib_error
from urllib import request as urllib_request

from core.dto.subtitle_dto import SubtitleSegmentDTO
from infrastructure.translation.base import (
    TranslationConfigurationError,
    TranslationResponseError,
)
from infrastructure.translation.batch_builder import TranslationBatch, TranslationBatchBuilder


JsonPayload = dict[str, object]
Transport = Callable[[str, dict[str, str], JsonPayload, float], JsonPayload]


class OpenAICompatibleTranslator:
    """调用 Chat Completions 兼容接口完成字幕批量翻译。"""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        api_key_env: str = "OPENAI_API_KEY",
        timeout_seconds: float = 60.0,
        max_retries: int = 2,
        batch_builder: TranslationBatchBuilder | None = None,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """保存接口配置，并在真正请求前解析 API 密钥。

        用户在软件内填写的密钥优先使用；为空时再读取环境变量。
        密钥不会进入请求正文、日志或异常文本。
        `transport` 是测试注入点；生产环境默认使用标准库 `urllib`。
        """

        if timeout_seconds <= 0:
            raise ValueError("翻译请求超时时间必须大于 0。")
        if max_retries < 0:
            raise ValueError("翻译最大重试次数不能小于 0。")
        self.base_url = base_url.strip()
        self.model = model.strip()
        self.api_key = api_key.strip()
        self.api_key_env = api_key_env
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.batch_builder = batch_builder or TranslationBatchBuilder()
        self.transport = transport
        self.sleep = sleep

    def translate_segments(
        self,
        segments: list[SubtitleSegmentDTO],
        source_language: str,
        target_language: str,
        context: str | None = None,
    ) -> list[SubtitleSegmentDTO]:
        """批量翻译字幕文本并按原顺序返回目标语言片段。"""

        if not segments or source_language == target_language:
            return [
                SubtitleSegmentDTO(
                    segment_id=segment.segment_id,
                    start_ms=segment.start_ms,
                    end_ms=segment.end_ms,
                    text=segment.text,
                    language=target_language,
                )
                for segment in segments
            ]

        self._validate_configuration()
        batches = self.batch_builder.build_batches(
            segments=segments,
            source_language=source_language,
            target_language=target_language,
            context=context,
        )
        translated_by_id: dict[str, str] = {}

        # 批次按字幕原始顺序发送，响应只负责填充文本，
        # 这样时间轴和字幕顺序始终来自本地原始数据。
        for batch in batches:
            response = self._request_with_retry(batch)
            for segment_id, text in self._parse_translations(response, batch):
                translated_by_id[segment_id] = text

        missing_ids = [segment.segment_id for segment in segments if segment.segment_id not in translated_by_id]
        if missing_ids:
            raise TranslationResponseError(
                f"翻译响应缺少字幕编号：{', '.join(missing_ids[:5])}"
            )

        return [
            SubtitleSegmentDTO(
                segment_id=segment.segment_id,
                start_ms=segment.start_ms,
                end_ms=segment.end_ms,
                text=translated_by_id[segment.segment_id],
                language=target_language,
            )
            for segment in segments
        ]

    def _validate_configuration(self) -> None:
        """在首次网络请求前检查地址、模型和密钥配置。"""

        if not self.base_url:
            raise TranslationConfigurationError("翻译接口地址尚未配置。")
        if not self.model:
            raise TranslationConfigurationError("翻译模型尚未配置。")
        if not self._resolved_api_key():
            raise TranslationConfigurationError("翻译 API 密钥尚未配置。")

    def _request_with_retry(self, batch: TranslationBatch) -> JsonPayload:
        """发送一个批次，并对网络或服务端临时错误做指数退避重试。"""

        payload = self._build_payload(batch)
        endpoint = self._endpoint()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._resolved_api_key()}",
        }

        for attempt in range(self.max_retries + 1):
            try:
                if self.transport is not None:
                    return self.transport(endpoint, headers, payload, self.timeout_seconds)
                return self._send_http(endpoint, headers, payload)
            except urllib_error.HTTPError as exc:
                if not self._is_retryable_status(exc.code) or attempt >= self.max_retries:
                    raise TranslationResponseError(
                        f"翻译服务请求失败，HTTP 状态码：{exc.code}"
                    ) from exc
            except (urllib_error.URLError, TimeoutError, OSError) as exc:
                if attempt >= self.max_retries:
                    raise TranslationResponseError("翻译服务网络请求失败。") from exc

            self.sleep(2**attempt)

        raise TranslationResponseError("翻译请求未得到有效结果。")

    def _send_http(
        self,
        endpoint: str,
        headers: dict[str, str],
        payload: JsonPayload,
    ) -> JsonPayload:
        """使用标准库发送 JSON 请求并解析 JSON 响应。"""

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib_request.Request(endpoint, data=body, headers=headers, method="POST")
        with urllib_request.urlopen(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    def _build_payload(self, batch: TranslationBatch) -> JsonPayload:
        """构造只包含字幕文本和必要语言上下文的请求体。"""

        items = [
            {"id": segment.segment_id, "text": segment.text}
            for segment in batch.segments
        ]
        instructions = (
            "你是字幕翻译器。只翻译字幕正文，不解释、不合并、不删除条目。"
            "必须返回 JSON 数组，每项包含原样保留的 id 和翻译后的 text。"
        )
        user_payload = {
            "source_language": batch.source_language,
            "target_language": batch.target_language,
            "context": batch.context,
            "segments": items,
        }
        return {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": instructions},
                {
                    "role": "user",
                    "content": json.dumps(user_payload, ensure_ascii=False),
                },
            ],
        }

    def _parse_translations(
        self,
        response: JsonPayload,
        batch: TranslationBatch,
    ) -> list[tuple[str, str]]:
        """解析模型返回的 JSON 数组，并校验编号与文本完整性。"""

        try:
            choices = response["choices"]
            content = choices[0]["message"]["content"]  # type: ignore[index]
            parsed = json.loads(self._strip_code_fence(str(content)))
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise TranslationResponseError("翻译服务返回内容无法解析。") from exc

        if isinstance(parsed, dict):
            parsed = parsed.get("translations")
        if not isinstance(parsed, list):
            raise TranslationResponseError("翻译响应不是字幕数组。")

        if all(isinstance(item, dict) and "id" in item for item in parsed):
            result: list[tuple[str, str]] = []
            for item in parsed:
                text = item.get("text")
                if not isinstance(text, str) or not text.strip():
                    raise TranslationResponseError("翻译响应包含空字幕文本。")
                result.append((str(item["id"]), text.strip()))
            return result

        if len(parsed) != len(batch.segments) or not all(
            isinstance(item, str) and item.strip() for item in parsed
        ):
            raise TranslationResponseError("翻译响应条目数量或格式不正确。")
        return [
            (segment.segment_id, str(text).strip())
            for segment, text in zip(batch.segments, parsed, strict=True)
        ]

    def _strip_code_fence(self, content: str) -> str:
        """去掉模型偶尔包裹 JSON 的 Markdown 代码围栏。"""

        stripped = content.strip()
        if stripped.startswith("```") and stripped.endswith("```"):
            lines = stripped.splitlines()
            return "\n".join(lines[1:-1]).strip()
        return stripped

    def _endpoint(self) -> str:
        """把基础地址规整成 Chat Completions 请求地址。"""

        endpoint = self.base_url.rstrip("/")
        if not endpoint.endswith("/chat/completions"):
            endpoint = f"{endpoint}/chat/completions"
        return endpoint

    def _is_retryable_status(self, status_code: int) -> bool:
        """判断 HTTP 状态是否通常表示临时服务问题。"""

        return status_code == 429 or 500 <= status_code < 600

    def _resolved_api_key(self) -> str:
        """优先返回软件内配置的密钥，再尝试环境变量兜底。"""

        if self.api_key:
            return self.api_key
        if not self.api_key_env:
            return ""
        return os.getenv(self.api_key_env, "").strip()
