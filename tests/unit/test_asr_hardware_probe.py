"""本地 ASR 硬件探测测试。

测试通过伪 `CTranslate2` 模块和显卡信息读取器覆盖推荐规则，
不会真正占用 GPU，也不依赖测试机器安装 NVIDIA 驱动。
"""

from infrastructure.asr.hardware_probe import CTranslate2HardwareProbe


class FakeCTranslate2:
    """返回测试指定的 CUDA 数量和计算精度。"""

    def __init__(self, device_count: int, compute_types: set[str]) -> None:
        self.device_count = device_count
        self.compute_types = compute_types

    def get_cuda_device_count(self) -> int:
        """返回可见 CUDA 设备数量。"""

        return self.device_count

    def get_supported_compute_types(self, device: str, device_index: int) -> set[str]:
        """返回第一块 CUDA 设备支持的精度集合。"""

        assert device == "cuda"
        assert device_index == 0
        return self.compute_types


def test_probe_recommends_medium_float16_for_six_gigabyte_gpu() -> None:
    """6GB NVIDIA GPU 应推荐质量更高的 `medium + float16`。"""

    # arrange
    probe = CTranslate2HardwareProbe(
        ctranslate_module=FakeCTranslate2(1, {"float16", "int8_float16", "int8"}),
        gpu_metadata_reader=lambda: ("RTX 4050 Laptop GPU", 6_141),
    )

    # act
    result = probe.probe()

    # assert
    assert result.cuda_available is True
    assert result.recommended_model == "medium"
    assert result.recommended_device == "cuda"
    assert result.recommended_compute_type == "float16"
    assert result.vram_mb == 6_141
    assert "RTX 4050" in result.diagnostic_message


def test_probe_recommends_small_when_gpu_memory_is_below_five_gigabytes() -> None:
    """显存较小时应保留 GPU 加速，但推荐更稳妥的 `small`。"""

    probe = CTranslate2HardwareProbe(
        ctranslate_module=FakeCTranslate2(1, {"int8_float16", "int8"}),
        gpu_metadata_reader=lambda: ("Laptop GPU", 4_096),
    )

    result = probe.probe()

    assert result.cuda_available is True
    assert result.recommended_model == "small"
    assert result.recommended_compute_type == "int8_float16"


def test_probe_falls_back_to_cpu_when_cuda_is_unavailable() -> None:
    """没有可用 CUDA 设备时应返回可直接运行的 CPU 配置。"""

    probe = CTranslate2HardwareProbe(
        ctranslate_module=FakeCTranslate2(0, set()),
        gpu_metadata_reader=lambda: ("", None),
    )

    result = probe.probe()

    assert result.cuda_available is False
    assert result.recommended_model == "small"
    assert result.recommended_device == "cpu"
    assert result.recommended_compute_type == "int8"
