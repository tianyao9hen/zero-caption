"""字幕烧录导出适配器。"""

from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess
from uuid import uuid4

from core.domain.enums import ExportMode
from core.dto.task_dto import ExportRecordDTO, ExportVideoInput


class BurnInExporter:
    """通过 FFmpeg 将 ASS/SRT 字幕渲染进视频画面。"""

    def __init__(self, ffmpeg_path: str | Path = "ffmpeg") -> None:
        """保存 FFmpeg 路径；导出时才解析可执行文件。"""

        self.ffmpeg_path = Path(ffmpeg_path)

    def export(self, request: ExportVideoInput) -> ExportRecordDTO:
        """执行烧录命令并返回导出记录。

        烧录结果会先写入成品目录中的临时文件。只有 `FFmpeg` 完整成功后，
        临时文件才会原子替换正式成品，避免中断的重新导出破坏上一次结果。
        """

        if request.mode is not ExportMode.BURN_IN:
            raise ValueError("烧录导出器只支持 BURN_IN 模式。")
        if not request.source_video.is_file():
            raise FileNotFoundError(f"未找到源视频：{request.source_video}")
        if not request.subtitle_path.is_file():
            raise FileNotFoundError(f"未找到字幕文件：{request.subtitle_path}")

        executable = self._resolve_executable()
        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        subtitle_filter = self._subtitle_filter_path(request.subtitle_path)
        staged_output_path = self._staged_output_path(request.output_path)
        command = [
            str(executable),
            "-hide_banner",
            "-nostdin",
            "-nostats",
            "-y",
            "-i",
            str(request.source_video),
            "-vf",
            f"subtitles={subtitle_filter}",
            "-c:a",
            "copy",
            str(staged_output_path),
        ]
        try:
            completed = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                # 烧录过程可能持续很久，Windows 桌面版必须让控制台型
                # `FFmpeg` 始终在后台运行，不能把终端窗口暴露给用户。
                creationflags=(
                    subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                ),
            )
            if completed.returncode != 0:
                raise RuntimeError(self._failure_message(completed))
            if not staged_output_path.is_file():
                raise RuntimeError("FFmpeg 已结束，但没有生成烧录视频。")

            # 同目录替换不会跨磁盘移动，可以让旧成品一直保留到新成品
            # 完整写出。即使替换失败，下面的清理也只删除本次临时文件。
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

    @staticmethod
    def _staged_output_path(output_path: Path) -> Path:
        """为本次烧录生成与正式成品位于同一目录的唯一临时路径。"""

        return output_path.with_name(
            f".{output_path.stem}.{uuid4().hex}.zero-caption-part"
            f"{output_path.suffix}"
        )

    @staticmethod
    def _failure_message(completed: subprocess.CompletedProcess[str]) -> str:
        """把冗长的 `FFmpeg` 输出收敛成适合任务页展示的错误摘要。"""

        detail = (completed.stderr or completed.stdout or "").strip()
        if "received signal 15" in detail:
            return (
                "FFmpeg 烧录被外部中断。请保持 Zero Caption 运行后重新导出。"
            )
        if not detail:
            return f"FFmpeg 烧录失败，退出码：{completed.returncode}。"

        # 媒体工具可能输出数万字符的逐帧进度。只保留最后二十行，既包含
        # 真正错误，也避免 SQLite 和任务详情被无关进度文本撑满。
        detail_tail = "\n".join(detail.splitlines()[-20:])
        return (
            f"FFmpeg 烧录失败，退出码：{completed.returncode}。\n"
            f"{detail_tail}"
        )
