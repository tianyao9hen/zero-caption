"""字幕烧录导出适配器。"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys
from threading import Thread
from uuid import uuid4

from core.domain.enums import ExportMode
from core.dto.task_dto import ExportRecordDTO, ExportVideoInput

# 烧录必须重新编码整段视频。默认 preset 对两小时视频过慢，这里显式使用
# 更快的预设，并保留常见播放器都支持的像素格式。
_BURN_IN_ENCODER_ARGS = ("-c:v", "libx264", "-preset", "veryfast", "-crf", "23")

# `FFmpeg` 统计块的行首关键字。失败摘要里需要剔除这些行，否则错误信息
# 会被每秒两次的进度统计完全淹没。
_PROGRESS_LINE_PATTERN = re.compile(
    r"(frame|fps|stream_\d+_\d+_q|bitrate|total_size|out_time|dup_frames|"
    r"drop_frames|speed|progress)\s*="
)


class BurnInExporter:
    """通过 FFmpeg 将 ASS/SRT 字幕渲染进视频画面。"""

    def __init__(self, ffmpeg_path: str | Path = "ffmpeg") -> None:
        """保存 FFmpeg 路径；导出时才解析可执行文件。"""

        self.ffmpeg_path = Path(ffmpeg_path)

    def export(self, request: ExportVideoInput) -> ExportRecordDTO:
        """执行烧录命令并返回导出记录。

        烧录结果会先写入成品目录中的临时文件。只有 `FFmpeg` 完整成功后，
        临时文件才会原子替换正式成品，避免中断的重新导出破坏上一次结果。

        烧录会重新编码整段视频，耗时可能达到数十分钟。适配器在执行期间
        通过 `request.progress_callback` 持续回报已处理时长，界面因此不会
        停在“已开始”却没有反馈的状态。
        """

        if request.mode is not ExportMode.BURN_IN:
            raise ValueError("烧录导出器只支持 BURN_IN 模式。")
        if not request.source_video.is_file():
            raise FileNotFoundError(
                f"未找到源视频：{request.source_video}。"
                "烧录需要读取原始视频文件，请确认它没有被移动或删除。"
            )
        if not request.subtitle_path.is_file():
            raise FileNotFoundError(f"未找到字幕文件：{request.subtitle_path}")

        executable = self._resolve_executable()
        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        subtitle_filter = self._subtitle_filter_path(request.subtitle_path)
        staged_output_path = self._staged_output_path(request.output_path)
        total_ms = self._probe_duration_ms(executable, request.source_video)
        # 这里不能加 `-nostats`。`FFmpeg` 的 `-progress` 报告与终端统计由
        # 同一段代码写出，禁用统计后进度文件也会变成空文件。统计信息改由
        # `stderr` 后台线程读走，并在失败摘要里过滤掉，不影响错误可读性。
        command = [
            str(executable),
            "-hide_banner",
            "-nostdin",
            "-progress",
            "pipe:1",
            "-y",
            "-i",
            str(request.source_video),
            "-vf",
            f"subtitles={subtitle_filter}",
            *_BURN_IN_ENCODER_ARGS,
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            str(staged_output_path),
        ]
        try:
            failure = self._run_ffmpeg(
                command,
                progress_callback=request.progress_callback,
                total_ms=total_ms,
            )
            if failure is not None:
                # 源视频的音轨编码可能不被目标容器接受。此时不直接判定失败，
                # 而是改用通用音频编码重试一次，让 `.mkv`、`.avi` 等来源也能
                # 正常烧录，而不是让用户只看到一条难懂的 FFmpeg 报错。
                if not self._is_audio_copy_failure(failure):
                    raise RuntimeError(failure)
                retried_command = [
                    part if part != "copy" else "aac" for part in command
                ]
                failure = self._run_ffmpeg(
                    retried_command,
                    progress_callback=request.progress_callback,
                    total_ms=total_ms,
                )
                if failure is not None:
                    raise RuntimeError(failure)
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
        """解析项目资源或系统 PATH 中的 FFmpeg。

        打包运行时当前工作目录通常是安装目录或用户目录，配置里的相对路径
        不一定存在。因此这里与识别用的 `FFmpegAdapter` 保持同一套候选顺序：
        配置路径、随包资源目录、`PATH`，确保安装版也能找到可执行文件。
        """

        if self.ffmpeg_path.exists():
            return self.ffmpeg_path
        for candidate in self._bundle_candidates():
            if candidate.exists():
                return candidate
        resolved = shutil.which(self.ffmpeg_path.name)
        if resolved:
            return Path(resolved)
        raise FileNotFoundError(f"未找到 FFmpeg：{self.ffmpeg_path}")

    @staticmethod
    def _bundle_candidates() -> list[Path]:
        """返回应用内置 FFmpeg 的候选路径。"""

        candidates = [
            Path(__file__).resolve().parents[2]
            / "resources"
            / "bin"
            / "ffmpeg"
            / "ffmpeg.exe"
        ]
        bundle_root = getattr(sys, "_MEIPASS", None)
        if bundle_root:
            candidates.insert(
                0,
                Path(bundle_root) / "resources" / "bin" / "ffmpeg" / "ffmpeg.exe",
            )
        return candidates

    def _probe_duration_ms(
        self,
        executable: Path,
        source_video: Path,
    ) -> int:
        """读取源视频总时长，用于把烧录进度换算成百分比。

        探测失败时返回 0。这种情况下界面只显示已处理时长，不会因此中断
        真正的烧录任务。
        """

        completed = subprocess.run(
            [str(executable), "-hide_banner", "-nostats", "-i", str(source_video)],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
        )
        detail = f"{completed.stderr}\n{completed.stdout}"
        match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", detail)
        if match is None:
            return 0
        hours, minutes, seconds = match.groups()
        return round(
            (int(hours) * 3_600 + int(minutes) * 60 + float(seconds)) * 1_000
        )

    def _run_ffmpeg(
        self,
        command: list[str],
        progress_callback: Callable[[int, int], None] | None,
        total_ms: int,
    ) -> str | None:
        """执行一次烧录命令。

        返回：
            `None` 表示成功；否则返回适合界面展示的错误摘要。

        `FFmpeg` 的进度写在 `stdout`，错误写在 `stderr`。这里边跑边读进度，
        避免长时间烧录期间界面完全没有反馈。
        """

        # 两条管道都必须被持续读走。只读取进度而不读取 `stderr` 时，
        # 一旦 `FFmpeg` 输出的错误信息超过管道缓冲区，它会停在写入处等待，
        # 表现为界面一直显示“正在生成”却不再前进。
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
        )
        assert process.stderr is not None
        # 只保留最后若干行。`FFmpeg` 每秒会写两次统计块，长视频运行一小时
        # 会产生近十万行输出，全部留在内存里没有意义。
        collected_stderr: deque[str] = deque(maxlen=400)

        def drain_stderr() -> None:
            """在独立线程里读走错误输出，避免主流程等待进度时被阻塞。"""

            for line in process.stderr:
                collected_stderr.append(line)

        stderr_thread = Thread(target=drain_stderr, daemon=True)
        stderr_thread.start()

        progress_key = "out_time="
        assert process.stdout is not None
        try:
            for line in process.stdout:
                if progress_callback is None:
                    continue
                if not line.startswith(progress_key):
                    continue
                # 优先解析 `out_time=HH:MM:SS.ffffff`。某些 `FFmpeg` 版本的
                # `out_time_ms` 实际写的是微秒，直接按毫秒使用会算出错误百分比。
                match = re.match(
                    r"out_time=(\d+):(\d+):(\d+(?:\.\d+)?)",
                    line.strip(),
                )
                if match is None:
                    continue
                hours, minutes, seconds = match.groups()
                processed_ms = round(
                    (int(hours) * 3_600 + int(minutes) * 60 + float(seconds))
                    * 1_000
                )
                progress_callback(processed_ms, total_ms)
        finally:
            process.stdout.close()

        process.wait()
        stderr_thread.join(timeout=5)
        if process.returncode != 0:
            return self._failure_message(
                process.returncode,
                "".join(collected_stderr),
            )
        return None

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
    def _is_audio_copy_failure(message: str) -> bool:
        """判断失败是否来自直接复制音轨，从而值得改用重编码重试。"""

        lowered = message.lower()
        return (
            "could not find tag for codec" in lowered
            or "codec not currently supported in container" in lowered
            or "incorrect codec parameters" in lowered
            or "audio" in lowered
            and "not supported" in lowered
        )

    @staticmethod
    def _failure_message(returncode: int, detail: str) -> str:
        """把冗长的 `FFmpeg` 输出收敛成适合任务页展示的错误摘要。"""

        detail = detail.strip()
        if "received signal 15" in detail:
            return "FFmpeg 烧录被外部中断。请保持 Zero Caption 运行后重新导出。"
        if not detail:
            return f"FFmpeg 烧录失败，退出码：{returncode}。"

        # 统计块会混在 `stderr` 里。先过滤掉 `frame=`、`speed=` 这类进度行，
        # 再保留最后二十行，才能真正把失败原因展示给用户。
        lines = [
            line
            for line in detail.splitlines()
            if not _PROGRESS_LINE_PATTERN.match(line.strip())
        ]
        detail_tail = "\n".join(lines[-20:])
        if not detail_tail:
            return f"FFmpeg 烧录失败，退出码：{returncode}。"
        return f"FFmpeg 烧录失败，退出码：{returncode}。\n{detail_tail}"
