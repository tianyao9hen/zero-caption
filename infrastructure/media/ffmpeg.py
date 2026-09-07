"""FFmpeg 抽音频适配器。"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class FFmpegError(RuntimeError):
    """FFmpeg 执行失败时抛出的异常，并保留可诊断的命令输出。"""

    command: list[str]
    returncode: int | None
    stderr: str

    def __str__(self) -> str:
        """返回适合任务页和错误对话框展示的简短错误摘要。"""

        detail = (self.stderr or "").strip()
        lines = [line.strip() for line in detail.splitlines() if line.strip()]
        # FFmpeg 可能输出数万行逐帧错误。只保留末尾少量信息，避免把
        # SQLite 任务记录和 Qt 对话框撑爆，同时保留真正的失败原因。
        tail = "\n".join(lines[-20:])
        if any("aac" in line.lower() for line in lines):
            message = "源视频音轨无法解码，可能包含损坏的 AAC 音频数据。"
        else:
            message = f"FFmpeg 抽取音频失败，退出码：{self.returncode}。"
        return f"{message}\n{tail}" if tail else message


class FFmpegAdapter:
    """负责把视频中的音轨抽取成单独音频文件。"""

    def __init__(self, ffmpeg_path: str | Path | None = "ffmpeg") -> None:
        self.ffmpeg_path = Path(ffmpeg_path) if ffmpeg_path is not None else None

    def resolve_executable(self) -> Path:
        """解析可执行文件路径，优先使用随包资源。"""

        if self.ffmpeg_path is not None:
            if self.ffmpeg_path.exists():
                return self.ffmpeg_path
            if self.ffmpeg_path.name not in {"ffmpeg", "ffmpeg.exe"}:
                raise FileNotFoundError(f"未找到 ffmpeg 可执行文件: {self.ffmpeg_path}")

        for candidate in self._bundle_candidates():
            if candidate.exists():
                return candidate

        fallback_name = self.ffmpeg_path.name if self.ffmpeg_path is not None else "ffmpeg"
        fallback = shutil.which(fallback_name)
        if fallback:
            return Path(fallback)

        raise FileNotFoundError("未找到 ffmpeg，可执行文件既不在随包目录也不在 PATH 中。")

    def _bundle_candidates(self) -> list[Path]:
        """返回应用内置的候选可执行文件路径。"""

        candidates = [Path(__file__).resolve().parents[2] / "resources" / "bin" / "ffmpeg" / "ffmpeg.exe"]
        bundle_root = getattr(sys, "_MEIPASS", None)
        if bundle_root:
            candidates.insert(0, Path(bundle_root) / "resources" / "bin" / "ffmpeg" / "ffmpeg.exe")
        return candidates

    def extract_audio(self, source_path: Path, output_path: Path) -> Path:
        """把视频中的音频抽取到指定目标文件。

        识别缓存统一转换成 `16kHz` 单声道。Whisper 最终也会使用这个格式，
        提前转换可以显著减小长视频的临时文件，同时避免每个识别块重复下混。
        """

        output_path.parent.mkdir(parents=True, exist_ok=True)
        executable = self.resolve_executable()
        codec_args = self._build_codec_args(output_path)
        command = [
            str(executable),
            "-y",
            "-i",
            str(source_path),
            "-vn",
            *codec_args,
            str(output_path),
        ]

        completed = self._run(command)
        if completed.returncode != 0:
            # FFmpeg 失败时可能已经写出一个不完整的 WAV。残缺文件不能
            # 留在 `temp/` 中，否则下次重试会被误判为可复用的成功缓存。
            output_path.unlink(missing_ok=True)
            raise FFmpegError(
                command=command,
                returncode=completed.returncode,
                stderr=completed.stderr or completed.stdout,
            )

        return output_path

    def extract_audio_segment(
        self,
        source_path: Path,
        output_path: Path,
        start_ms: int,
        end_ms: int,
    ) -> Path:
        """把音频的指定时间范围裁剪成独立识别文件。

        参数使用原始音频时间轴上的毫秒值。输出失败时会删除不完整文件，
        避免任务恢复时把半成品误当成可复用缓存。
        """

        if start_ms < 0 or end_ms <= start_ms:
            raise ValueError("音频片段时间范围无效。")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        executable = self.resolve_executable()
        duration_seconds = (end_ms - start_ms) / 1000
        command = [
            str(executable),
            "-y",
            "-ss",
            f"{start_ms / 1000:.3f}",
            "-i",
            str(source_path),
            "-t",
            f"{duration_seconds:.3f}",
            "-vn",
            *self._build_codec_args(output_path),
            str(output_path),
        ]
        completed = self._run(command)
        if completed.returncode != 0:
            output_path.unlink(missing_ok=True)
            raise FFmpegError(
                command=command,
                returncode=completed.returncode,
                stderr=completed.stderr or completed.stdout,
            )
        return output_path

    def _build_codec_args(self, output_path: Path) -> list[str]:
        """根据目标扩展名选择最小可用编码参数。"""

        suffix = output_path.suffix.lower()
        if suffix == ".wav":
            return ["-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le"]
        if suffix == ".flac":
            return ["-ac", "1", "-ar", "16000", "-acodec", "flac"]
        raise ValueError(f"暂不支持的音频输出格式: {output_path.suffix}")

    def _run(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        """执行一次 FFmpeg 命令并统一 Windows 子进程参数。"""

        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
        )
