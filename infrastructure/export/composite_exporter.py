"""按导出模式选择具体视频导出适配器。"""

from __future__ import annotations

from dataclasses import dataclass

from core.domain.enums import ExportMode
from core.dto.task_dto import ExportRecordDTO, ExportVideoInput
from core.ports.exporter import VideoExporter


@dataclass(slots=True)
class CompositeVideoExporter:
    """把不同导出模式路由到对应基础设施实现。"""

    exporters: dict[ExportMode, VideoExporter]

    def export(self, request: ExportVideoInput) -> ExportRecordDTO:
        """根据请求模式调用一个具体导出器。"""

        exporter = self.exporters.get(request.mode)
        if exporter is None:
            raise ValueError(f"未配置导出模式：{request.mode.value}")
        return exporter.export(request)
