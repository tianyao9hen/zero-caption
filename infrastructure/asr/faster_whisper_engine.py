"""`faster-whisper` 本地 ASR 适配器。

这个文件属于 infrastructure 层，职责是把第三方库 `faster-whisper`
暴露出来的识别结果转换成项目自己的 `SubtitleSegmentDTO`。
它只处理“如何调用模型”和“如何整理原始片段”，
不负责字幕去重、断句或 `SRT` 写出。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from core.dto.subtitle_dto import SubtitleSegmentDTO
from infrastructure.asr.cuda_runtime import prepare_cuda_runtime


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
        allow_cpu_fallback: bool = True,
        fallback_model_name: str | None = None,
        fallback_compute_type: str = "int8",
        model_factory: Callable[..., Any] | None = None,
    ) -> None:
        """保存构建模型所需的最小配置。

        参数：
            model_name：`faster-whisper` 使用的模型名或本地模型目录。
            device：推理设备，例如 `cpu` 或 `cuda`。
            compute_type：推理精度配置，例如 `int8` 或 `float16`。
            model_cache_dir：模型缓存目录。传相对路径时，将按当前工作目录解析。
            beam_size：解码时使用的束搜索宽度。
            vad_filter：是否启用内置的语音活动检测，减少纯静音片段。
            allow_cpu_fallback：CUDA 初始化失败时是否自动切换到 CPU。
            fallback_model_name：CPU 回退时使用的本地模型目录。
            fallback_compute_type：CPU 回退时使用的推理精度。
            model_factory：可选模型构造函数，供测试替换第三方实现。
        """

        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self.model_cache_dir = Path(model_cache_dir) if model_cache_dir is not None else None
        self.beam_size = beam_size
        self.vad_filter = vad_filter
        self.allow_cpu_fallback = allow_cpu_fallback
        self.fallback_model_name = fallback_model_name or model_name
        self.fallback_compute_type = fallback_compute_type
        self.model_factory = model_factory
        self.active_model_name = model_name
        self.active_device = device
        self.active_compute_type = compute_type
        self.fallback_reason = ""
        self._fallback_used = False
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

        try:
            return self._transcribe_once(source_path, language)
        except Exception as exc:
            # `faster-whisper` 的识别迭代是惰性的，CUDA 错误既可能在创建模型时，
            # 也可能在真正遍历片段时出现，因此回退边界必须覆盖完整识别过程。
            if not self._can_fallback(exc):
                raise
            self._activate_cpu_fallback(exc)
            return self._transcribe_once(source_path, language)

    def runtime_summary(self) -> str:
        """返回本次实际生效的模型、设备、精度和可选回退提示。"""

        model_name = Path(self.active_model_name).name
        active_summary = (
            f"实际使用 {model_name} + {self.active_device.upper()} + "
            f"{self.active_compute_type} 完成识别。"
        )
        if self.fallback_reason:
            return f"{self.fallback_reason}；{active_summary}"
        return active_summary

    def verify_runtime(
        self,
        audio_path: Path,
        language: str | None = None,
    ) -> str:
        """关闭静音过滤并执行一次真实模型计算，供发布包验收使用。

        普通字幕任务仍按用户配置使用语音活动检测。这里只在独立自检进程中
        临时关闭过滤，避免一秒静音在进入 GPU 编码器前就被跳过，造成动态库
        缺失却被误报为“模型加载成功”。
        """

        original_vad_filter = self.vad_filter
        self.vad_filter = False
        try:
            self.transcribe(audio_path, language=language)
        finally:
            self.vad_filter = original_vad_filter
        return self.runtime_summary()

    def _transcribe_once(
        self,
        source_path: Path,
        language: str | None,
    ) -> list[SubtitleSegmentDTO]:
        """使用当前活动设备执行一次识别，不在此方法内重复回退。"""

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

        model_cache_dir = None
        if self.model_cache_dir is not None:
            # 提前创建缓存目录，可以更早暴露权限问题，
            # 也让模型下载与复用位置保持稳定。
            self.model_cache_dir.mkdir(parents=True, exist_ok=True)
            model_cache_dir = str(self.model_cache_dir)

        try:
            self._model = self._create_model(
                model_name=self.active_model_name,
                device=self.active_device,
                compute_type=self.active_compute_type,
                model_cache_dir=model_cache_dir,
            )
        except Exception as exc:
            if not self._can_fallback(exc):
                raise
            self._activate_cpu_fallback(exc, model_cache_dir=model_cache_dir)
        return self._model

    def _create_model(
        self,
        model_name: str,
        device: str,
        compute_type: str,
        model_cache_dir: str | None,
    ) -> Any:
        """创建第三方模型对象，并保持依赖导入位于基础设施层。"""

        # NVIDIA 官方 Python 包把 `cuBLAS` 放在独立目录中，Windows 不会自动
        # 搜索这个位置。模型初始化前显式注册目录，发布版才能真正执行 CUDA 推理，
        # 而不只是完成显卡探测后在第一段真实音频处失败。
        if device == "cuda":
            prepare_cuda_runtime()

        factory = self.model_factory
        if factory is None:
            try:
                from faster_whisper import WhisperModel
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "当前环境未安装 `faster-whisper`，无法运行本地 ASR。"
                ) from exc
            factory = WhisperModel
        return factory(
            model_name,
            device=device,
            compute_type=compute_type,
            download_root=model_cache_dir,
        )

    def _activate_cpu_fallback(
        self,
        error: Exception,
        model_cache_dir: str | None = None,
    ) -> None:
        """记录 CUDA 失败原因，并创建一次 CPU 回退模型。"""

        self._fallback_used = True
        self._model = None
        self.active_model_name = self.fallback_model_name
        self.active_device = "cpu"
        self.active_compute_type = self.fallback_compute_type
        self.fallback_reason = (
            f"CUDA 初始化或推理失败，已切换到 CPU：{type(error).__name__}"
        )
        if model_cache_dir is None and self.model_cache_dir is not None:
            model_cache_dir = str(self.model_cache_dir)
        try:
            self._model = self._create_model(
                model_name=self.active_model_name,
                device=self.active_device,
                compute_type=self.active_compute_type,
                model_cache_dir=model_cache_dir,
            )
        except Exception as fallback_error:
            raise RuntimeError("CUDA 失败后，CPU 回退模型也无法加载。") from fallback_error

    def _can_fallback(self, error: Exception) -> bool:
        """判断当前异常是否属于允许自动切换 CPU 的 CUDA 故障。"""

        if (
            not self.allow_cpu_fallback
            or self._fallback_used
            or self.active_device != "cuda"
        ):
            return False
        if isinstance(error, OSError):
            return True
        message = str(error).lower()
        return any(
            keyword in message
            for keyword in ("cuda", "cudnn", "cublas", "gpu", "out of memory")
        )

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
