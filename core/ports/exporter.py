"""视频导出抽象端口定义模块。"""

from __future__ import annotations

from typing import Protocol

from core.dto.task_dto import ExportRecordDTO, ExportVideoInput


class VideoExporter(Protocol):
    """把视频和字幕产物组合并导出的能力。"""

    def export(self, request: ExportVideoInput) -> ExportRecordDTO: ...
