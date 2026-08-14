"""字幕烧录导出适配器。"""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

from core.domain.enums import ExportMode
from core.dto.task_dto import ExportRecordDTO, ExportVideoInput


class BurnInExporter:
    """通过 FFmpeg 将 ASS/SRT 字幕渲染进视频画面。"""

    def __init__(self, ffmpeg_path: str | Path = "ffmpeg") -> None:
        """保存 FFmpeg 路径；导出时才解析可执行文件。"""

        self.ffmpeg_path = Path(ffmpeg_path)

    def export(self, request: ExportVideoInput) -> ExportRecordDTO:
        """执行烧录命令并返回导出记录。"""

        if request.mode is not ExportMode.BURN_IN:
            raise ValueError("烧录导出器只支持 BURN_IN 模式。")
        if not request.source_video.is_file():
            raise FileNotFoundError(f"未找到源视频：{request.source_video}")
        if not request.subtitle_path.is_file():
            raise FileNotFoundError(f"未找到字幕文件：{request.subtitle_path}")

        executable = self._resolve_executable()
        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        subtitle_filter = self._subtitle_filter_path(request.subtitle_path)
        command = [
            str(executable),
            "-y",
            "-i",
            str(request.source_video),
            "-vf",
            f"subtitles={subtitle_filter}",
            "-c:a",
            "copy",
            str(request.output_path),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr or completed.stdout or "FFmpeg 烧录失败")
        return ExportRecordDTO(
            project_id=request.project_id,
            source_video=request.source_video,
            subtitle_path=request.subtitle_path,
            output_path=request.output_path,
            mode=request.mode,
        )

    def _resolve_executable(self) -> Path:
        """解析项目资源或系统 PATH 中的 FFmpeg。"""

        if self.ffmpeg_path.exists():
            return self.ffmpeg_path
        resolved = shutil.which(self.ffmpeg_path.name)
        if resolved:
            return Path(resolved)
        raise FileNotFoundError(f"未找到 FFmpeg：{self.ffmpeg_path}")

    @staticmethod
    def _subtitle_filter_path(path: Path) -> str:
        """转义 Windows 路径，使其可以安全嵌入 FFmpeg filter 参数。"""

        return str(path.resolve()).replace("\\", "/").replace(":", r"\\:").replace("'", r"\\'")
