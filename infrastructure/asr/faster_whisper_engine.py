"""`faster-whisper` 本地 ASR 适配器。

这个文件属于 infrastructure 层，职责是把第三方库 `faster-whisper`
暴露出来的识别结果转换成项目自己的 `SubtitleSegmentDTO`。
它只处理“如何调用模型”和“如何整理原始片段”，
不负责字幕去重、断句或 `SRT` 写出。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.dto.subtitle_dto import SubtitleSegmentDTO


class FasterWhisperEngine:
    """把本地音频识别成字幕片段的 `faster-whisper` 适配器。

    这个类实现了 `AsrEngine` 端口要求的 `transcribe` 方法。
    为了减少启动时开销，模型对象会在第一次真正识别时才延迟创建。
    """

    def __init__(
        self,
        model_name: str = "small",
        device: str = "cpu",
        compute_type: str = "int8",
        model_cache_dir: Path | None = None,
        beam_size: int = 5,
        vad_filter: bool = True,
    ) -> None:
        """保存构建模型所需的最小配置。

        参数：
            model_name：`faster-whisper` 使用的模型名或本地模型目录。
            device：推理设备，例如 `cpu` 或 `cuda`。
            compute_type：推理精度配置，例如 `int8` 或 `float16`。
            model_cache_dir：模型缓存目录。传相对路径时，将按当前工作目录解析。
            beam_size：解码时使用的束搜索宽度。
            vad_filter：是否启用内置的语音活动检测，减少纯静音片段。
        """

        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self.model_cache_dir = Path(model_cache_dir) if model_cache_dir is not None else None
        self.beam_size = beam_size
        self.vad_filter = vad_filter
        self._model: Any | None = None

    def transcribe(
        self,
        audio_path: Path,
        language: str | None = None,
    ) -> list[SubtitleSegmentDTO]:
        """把音频文件识别成带时间轴的字幕片段列表。

        这个方法只保证返回 `core` 层需要的稳定 DTO。
        它不会在这里处理字幕清洗，因为那属于后续字幕后处理阶段的职责。
        """

        source_path = Path(audio_path)
        if not source_path.exists():
            raise FileNotFoundError(f"未找到待识别音频文件：{source_path}")

        model = self._get_model()
        segments, info = model.transcribe(
            str(source_path),
            language=language,
            beam_size=self.beam_size,
            vad_filter=self.vad_filter,
        )

        detected_language = language or getattr(info, "language", None) or "unknown"
        return self._build_segments(segments=segments, language=detected_language)

    def _get_model(self) -> Any:
        """延迟创建并缓存底层 `WhisperModel` 实例。"""

        if self._model is not None:
            return self._model

        try:
            from faster_whisper import WhisperModel
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "当前环境未安装 `faster-whisper`，无法运行本地 ASR。"
            ) from exc

        model_cache_dir = None
        if self.model_cache_dir is not None:
            # 提前创建缓存目录，可以更早暴露权限问题，
            # 也让模型下载与复用位置保持稳定。
            self.model_cache_dir.mkdir(parents=True, exist_ok=True)
            model_cache_dir = str(self.model_cache_dir)

        self._model = WhisperModel(
            self.model_name,
            device=self.device,
            compute_type=self.compute_type,
            download_root=model_cache_dir,
        )
        return self._model

    def _build_segments(
        self,
        segments: Any,
        language: str,
    ) -> list[SubtitleSegmentDTO]:
        """把第三方库片段对象转换成项目内部 DTO。"""

        results: list[SubtitleSegmentDTO] = []

        # `faster-whisper` 返回的是可迭代片段对象，而不是普通列表。
        # 这里显式迭代并逐段转换，便于后续在这个边界上补日志或调试信息。
        for index, segment in enumerate(segments, start=1):
            text = str(getattr(segment, "text", "")).strip()
            if not text:
                continue

            start_ms = max(0, int(round(float(getattr(segment, "start", 0.0)) * 1000)))
            end_ms = max(
                start_ms + 1,
                int(round(float(getattr(segment, "end", 0.0)) * 1000)),
            )
            results.append(
                SubtitleSegmentDTO(
                    segment_id=f"seg-{index}",
                    start_ms=start_ms,
                    end_ms=end_ms,
                    text=text,
                    language=language,
                )
            )

        return results
