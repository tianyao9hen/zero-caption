"""`faster-whisper` GPU 失败回退测试。

这些测试使用伪模型构造函数模拟 CUDA 动态库错误，保护自动回退规则，
不会加载真实模型或占用显存。
"""

import pytest

from infrastructure.asr.faster_whisper_engine import FasterWhisperEngine


class FakeModel:
    """返回空字幕和固定语言信息的轻量模型。"""

    def transcribe(self, *args, **kwargs):
        """模拟第三方模型的惰性片段与信息对象返回值。"""

        info = type("识别信息", (), {"language": "en"})()
        return [], info


class RecordingModel(FakeModel):
    """记录发布自检是否确实关闭了语音活动过滤。"""

    def __init__(self) -> None:
        self.vad_values: list[bool] = []

    def transcribe(self, *args, **kwargs):
        """保存本次过滤参数后复用轻量识别结果。"""

        self.vad_values.append(kwargs["vad_filter"])
        return super().transcribe(*args, **kwargs)


def test_cuda_initialization_failure_falls_back_to_cpu(tmp_path) -> None:
    """CUDA 依赖加载失败时应改用指定的 CPU 模型和 `int8` 精度。"""

    # arrange：第一个 CUDA 构造调用抛错，第二个 CPU 调用返回伪模型。
    calls: list[tuple[str, str, str]] = []

    def fake_factory(model_name, *, device, compute_type, download_root):
        calls.append((model_name, device, compute_type))
        if device == "cuda":
            raise RuntimeError("CUDA cublas library is unavailable")
        return FakeModel()

    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"fake audio")
    engine = FasterWhisperEngine(
        model_name="medium-model",
        device="cuda",
        compute_type="float16",
        fallback_model_name="small-model",
        fallback_compute_type="int8",
        model_factory=fake_factory,
    )

    # act
    segments = engine.transcribe(audio_path, language="en")

    # assert：只允许一次回退，并把实际生效参数留给日志和界面诊断。
    assert segments == []
    assert calls == [
        ("medium-model", "cuda", "float16"),
        ("small-model", "cpu", "int8"),
    ]
    assert engine.active_device == "cpu"
    assert engine.active_model_name == "small-model"
    assert engine.fallback_reason.startswith("CUDA 初始化或推理失败")
    assert "small-model + CPU + int8" in engine.runtime_summary()


def test_explicitly_disabled_cpu_fallback_preserves_cuda_error(tmp_path) -> None:
    """用户关闭 CPU 回退时，CUDA 错误应原样交给任务失败处理。"""

    def failing_factory(model_name, *, device, compute_type, download_root):
        raise RuntimeError("CUDA initialization failed")

    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"fake audio")
    engine = FasterWhisperEngine(
        model_name="medium-model",
        device="cuda",
        compute_type="float16",
        allow_cpu_fallback=False,
        model_factory=failing_factory,
    )

    with pytest.raises(RuntimeError, match="CUDA initialization failed"):
        engine.transcribe(audio_path, language="en")


def test_runtime_verification_forces_model_computation_without_vad(tmp_path) -> None:
    """发布自检应临时关闭静音过滤，并在结束后恢复普通任务配置。"""

    model = RecordingModel()
    audio_path = tmp_path / "silence.wav"
    audio_path.write_bytes(b"fake audio")
    engine = FasterWhisperEngine(
        model_name="medium-model",
        device="cuda",
        compute_type="float16",
        model_factory=lambda *args, **kwargs: model,
    )

    summary = engine.verify_runtime(audio_path, language="en")

    assert model.vad_values == [False]
    assert engine.vad_filter is True
    assert "medium-model + CUDA + float16" in summary
