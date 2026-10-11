"""按导出模式选择具体视频导出适配器。"""

from __future__ import annotations

from dataclasses import dataclass

from core.domain.enums import ExportMode
from core.dto.task_dto import ExportRecordDTO, ExportVideoInput
from core.ports.exporter import VideoExporter


@dataclass(slots=True)
class CompositeVideoExporter:
    """把不同导出模式路由到对应基础设施实现。

    除了按模式路由，它还负责识别“已经有现成成品”的请求：这类请求只需要
    复制文件，应该由 `prepared_exporter` 处理，而不是重新调用 `FFmpeg`。
    是否真的存在可用成品由核心用例判断，这里只做技术实现层面的分流。
    """

    exporters: dict[ExportMode, VideoExporter]
    prepared_exporter: VideoExporter | None = None

    def export(self, request: ExportVideoInput) -> ExportRecordDTO:
        """根据请求模式和是否携带现成成品选择具体导出器。"""

        if request.prepared_source_path is not None:
            if self.prepared_exporter is None:
                raise ValueError(
                    "本次导出要求复用预生成成品，但容器没有装配复制导出器。"
                )
            return self.prepared_exporter.export(request)

        exporter = self.exporters.get(request.mode)
        if exporter is None:
            raise ValueError(f"未配置导出模式：{request.mode.value}")
        return exporter.export(request)
