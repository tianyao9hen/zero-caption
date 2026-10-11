"""现成成品复制导出适配器。

用户选择了烧录字幕的任务，会在翻译完成后就先把成品视频烧录到项目自己的
`exports/` 目录里。等到用户点击“下载成品”时，不需要再花几十分钟重新编码，
只需要把这份已经存在的视频复制过去。
"""

from __future__ import annotations

from pathlib import Path
import shutil
from uuid import uuid4

from core.dto.task_dto import ExportRecordDTO, ExportVideoInput


class PreparedVideoExporter:
    """把项目目录内预生成的成品复制到用户选择的下载目录。"""

    def export(self, request: ExportVideoInput) -> ExportRecordDTO:
        """复制预生成成品并返回导出记录。

        参数：
            request：`prepared_source_path` 必须指向已经存在的项目内成品，
            `output_path` 是用户本次选择的下载位置。

        副作用：
            创建目标目录并写入成品文件；预生成成品和源字幕都保持原样，
            因此可以反复下载，不需要重新烧录。

        异常：
            `FileNotFoundError`：预生成成品已经不存在。此时调用方应回退到
            正常烧录流程，而不是把错误直接抛给用户。
        """

        prepared_source_path = request.prepared_source_path
        if prepared_source_path is None:
            raise ValueError("现成成品导出器必须先收到已预生成的成品路径。")
        if not prepared_source_path.is_file():
            raise FileNotFoundError(
                f"项目内的成品视频已不存在：{prepared_source_path}。"
                "请重新下载，应用会自动重新生成成品。"
            )

        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        # 先写同目录临时文件再替换，避免下载到一半中断时留下损坏视频，
        # 也避免覆盖上一次已经下载好的同名成品。
        staged_output_path = request.output_path.with_name(
            f".{request.output_path.stem}.{uuid4().hex}.zero-caption-part"
            f"{request.output_path.suffix}"
        )
        try:
            shutil.copyfile(prepared_source_path, staged_output_path)
            staged_output_path.replace(request.output_path)
        finally:
            staged_output_path.unlink(missing_ok=True)

        return ExportRecordDTO(
            project_id=request.project_id,
            source_video=request.source_video,
            subtitle_path=request.subtitle_path,
            output_path=request.output_path,
            mode=request.mode,
        )
