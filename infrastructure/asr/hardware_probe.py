"""本地 ASR 硬件探测适配器。

这个模块属于基础设施层，集中调用 `CTranslate2` 和 `nvidia-smi`，
把第三方运行时信息转换成核心层 DTO。界面层不应直接导入显卡库或执行命令。
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Callable

from core.dto.asr_dto import AsrHardwareInfoDTO


GpuMetadataReader = Callable[[], tuple[str, int | None]]


class CTranslate2HardwareProbe:
    """探测 NVIDIA CUDA 能力并给出适合笔记本的识别参数。"""

    def __init__(
        self,
        ctranslate_module: Any | None = None,
        gpu_metadata_reader: GpuMetadataReader | None = None,
    ) -> None:
        """保存可替换的探测协作者。

        参数：
            ctranslate_module：可选的 `CTranslate2` 模块，主要供测试注入。
            gpu_metadata_reader：可选的显卡名称和显存读取函数。

        探测过程不会加载 Whisper 模型，也不会占用大量显存。
        """

        self.ctranslate_module = ctranslate_module
        self.gpu_metadata_reader = gpu_metadata_reader or self._read_nvidia_smi

    def probe(self) -> AsrHardwareInfoDTO:
        """返回当前 CUDA 能力与推荐的模型、设备和精度组合。"""

        # 第一步：通过 `CTranslate2` 查询真正可用于推理的 CUDA 设备数。
        # 只看到显卡名称还不够，驱动或运行库缺失时这里会返回零或抛出异常。
        try:
            ctranslate2 = self.ctranslate_module or self._import_ctranslate2()
            device_count = int(ctranslate2.get_cuda_device_count())
        except (ImportError, OSError, RuntimeError, ValueError) as exc:
            return AsrHardwareInfoDTO.cpu_only(
                f"CUDA 探测失败，已使用 CPU 安全配置：{type(exc).__name__}"
            )

        if device_count <= 0:
            return AsrHardwareInfoDTO.cpu_only(
                "未检测到可用于 CTranslate2 的 CUDA 设备，将使用 CPU。"
            )

        # 第二步：查询设备真正支持的计算精度，避免在旧显卡上强行选择 `float16`。
        try:
            supported_types = tuple(
                sorted(ctranslate2.get_supported_compute_types("cuda", 0))
            )
        except (OSError, RuntimeError, ValueError) as exc:
            return AsrHardwareInfoDTO.cpu_only(
                f"CUDA 精度探测失败，已使用 CPU 安全配置：{type(exc).__name__}"
            )

        # 第三步：`nvidia-smi` 只补充名称和显存，不决定 CUDA 是否可用。
        # 命令缺失时仍保留 `CTranslate2` 的可靠结论，并使用保守推荐。
        gpu_name, vram_mb = self.gpu_metadata_reader()
        recommended_model = "medium" if vram_mb is None or vram_mb >= 5_120 else "small"
        recommended_compute_type = self._recommended_compute_type(supported_types)
        vram_text = f"，显存约 {vram_mb} MB" if vram_mb is not None else ""
        return AsrHardwareInfoDTO(
            cuda_available=True,
            device_count=device_count,
            gpu_name=gpu_name or "NVIDIA CUDA GPU",
            vram_mb=vram_mb,
            supported_compute_types=supported_types,
            recommended_model=recommended_model,
            recommended_device="cuda",
            recommended_compute_type=recommended_compute_type,
            diagnostic_message=(
                f"已检测到 {gpu_name or 'NVIDIA CUDA GPU'}{vram_text}，"
                f"推荐 {recommended_model} + CUDA + {recommended_compute_type}。"
            ),
        )

    def _import_ctranslate2(self) -> Any:
        """延迟导入 `CTranslate2`，让启动探针缺依赖时仍能给出可读结果。"""

        import ctranslate2

        return ctranslate2

    def _read_nvidia_smi(self) -> tuple[str, int | None]:
        """使用驱动自带命令读取第一块 NVIDIA GPU 的名称和总显存。"""

        executable = shutil.which("nvidia-smi")
        if executable is None and os.name == "nt":
            system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
            candidate = system_root / "System32" / "nvidia-smi.exe"
            if candidate.is_file():
                executable = str(candidate)
        if executable is None:
            return "NVIDIA CUDA GPU", None

        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            completed = subprocess.run(
                [
                    executable,
                    "--query-gpu=name,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                creationflags=creation_flags,
            )
            first_line = completed.stdout.splitlines()[0]
            name, memory_text = (part.strip() for part in first_line.split(",", 1))
            return name, int(float(memory_text))
        except (OSError, subprocess.SubprocessError, IndexError, ValueError):
            return "NVIDIA CUDA GPU", None

    def _recommended_compute_type(self, supported_types: tuple[str, ...]) -> str:
        """按质量优先顺序选择 GPU 推理精度。"""

        for compute_type in ("float16", "int8_float16", "int8"):
            if compute_type in supported_types:
                return compute_type
        return "auto"
