"""FFmpeg 抽音频适配器。"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class FFmpegError(RuntimeError):
    """FFmpeg 执行失败时抛出的异常。"""

    command: list[str]
    returncode: int | None
    stderr: str


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
        """把视频中的音频抽取到指定目标文件。"""

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

        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
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
            return ["-acodec", "pcm_s16le"]
        if suffix == ".flac":
            return ["-acodec", "flac"]
        raise ValueError(f"暂不支持的音频输出格式: {output_path.suffix}")
