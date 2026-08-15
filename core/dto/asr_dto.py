"""本地语音识别运行能力 DTO。

这个模块位于核心层，只描述硬件探测结果和推荐参数，不导入
`CTranslate2`、Qt 或操作系统命令。基础设施层负责产生这些数据，
应用层和界面层通过稳定 DTO 消费，避免跨层传递第三方对象。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AsrHardwareInfoDTO:
    """描述当前机器可用于本地字幕识别的计算能力。

    `frozen=True` 让探测结果成为只读快照，防止界面展示过程中被意外修改。
    推荐值只代表适合当前硬件的安全起点，用户仍可以在设置页显式覆盖。
    """

    cuda_available: bool
    device_count: int
    gpu_name: str
    vram_mb: int | None
    supported_compute_types: tuple[str, ...]
    recommended_model: str
    recommended_device: str
    recommended_compute_type: str
    diagnostic_message: str

    @classmethod
    def cpu_only(cls, diagnostic_message: str) -> "AsrHardwareInfoDTO":
        """创建一个使用 `small + CPU + int8` 的安全回退快照。"""

        return cls(
            cuda_available=False,
            device_count=0,
            gpu_name="未检测到可用的 NVIDIA GPU",
            vram_mb=None,
            supported_compute_types=("int8", "float32"),
            recommended_model="small",
            recommended_device="cpu",
            recommended_compute_type="int8",
            diagnostic_message=diagnostic_message,
        )
