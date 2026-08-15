"""应用容器的 ASR 自动配置测试。

硬件探测属于基础设施层，容器负责把用户的 `auto` 选项解析成实际模型、
设备和精度。本测试保护这条装配边界，不加载真实模型。
"""

import logging
from pathlib import Path

from app.container import AppContainer
from config.settings import AsrSettings, EngineSettings, Settings
from core.dto.asr_dto import AsrHardwareInfoDTO
from infrastructure.storage.workspace import WorkspaceManager


def gpu_hardware_info() -> AsrHardwareInfoDTO:
    """返回固定的 6GB CUDA 硬件快照。"""

    return AsrHardwareInfoDTO(
        cuda_available=True,
        device_count=1,
        gpu_name="RTX 4050 Laptop GPU",
        vram_mb=6_141,
        supported_compute_types=("float16", "int8", "int8_float16"),
        recommended_model="medium",
        recommended_device="cuda",
        recommended_compute_type="float16",
        diagnostic_message="测试推荐。",
    )


def create_container(tmp_path: Path, settings: Settings, hardware: AsrHardwareInfoDTO):
    """创建使用临时数据库和固定硬件快照的应用容器。"""

    workspace = WorkspaceManager(tmp_path / "workspace")
    workspace.ensure_structure()
    return AppContainer(
        settings=settings,
        workspace=workspace,
        logger=logging.getLogger("test-asr-runtime"),
        asr_hardware_info=hardware,
    )


def test_auto_configuration_uses_medium_cuda_on_six_gigabyte_gpu(tmp_path) -> None:
    """自动设置在 6GB GPU 上应选择内置 `medium + CUDA + float16`。"""

    container = create_container(tmp_path, Settings(), gpu_hardware_info())

    engine = container.create_asr_engine()

    assert Path(engine.model_name).name == "medium"
    assert engine.device == "cuda"
    assert engine.compute_type == "float16"
    assert Path(engine.fallback_model_name).name == "small"


def test_auto_configuration_uses_small_int8_when_only_cpu_is_available(
    tmp_path,
) -> None:
    """没有 CUDA 时自动设置应直接选择内置 `small + CPU + int8`。"""

    container = create_container(
        tmp_path,
        Settings(),
        AsrHardwareInfoDTO.cpu_only("测试使用 CPU。"),
    )

    engine = container.create_asr_engine()

    assert Path(engine.model_name).name == "small"
    assert engine.device == "cpu"
    assert engine.compute_type == "int8"


def test_user_can_override_auto_recommendation_with_small_cpu(tmp_path) -> None:
    """用户显式选择的 `small + CPU` 应优先于硬件推荐。"""

    settings = Settings(
        engine=EngineSettings(
            asr=AsrSettings(
                model_name="small",
                device="cpu",
                compute_type="int8",
            )
        )
    )
    container = create_container(tmp_path, settings, gpu_hardware_info())

    engine = container.create_asr_engine()

    assert Path(engine.model_name).name == "small"
    assert engine.device == "cpu"
    assert engine.compute_type == "int8"
