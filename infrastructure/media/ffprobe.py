"""ffprobe 适配器。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from core.dto.media_dto import AudioStreamDTO, MediaProbeResultDTO, VideoStreamDTO


@dataclass(slots=True)
class FFprobeError(RuntimeError):
    """ffprobe 执行失败时抛出的异常，并保留可诊断的命令输出。"""

    command: list[str]
    returncode: int | None
    stderr: str

    def __str__(self) -> str:
        """返回适合任务页展示的探测失败摘要。"""

        detail = (self.stderr or "").strip()
        lines = [line.strip() for line in detail.splitlines() if line.strip()]
        tail = "\n".join(lines[-20:])
        message = f"ffprobe 探测媒体失败，退出码：{self.returncode}。"
        return f"{message}\n{tail}" if tail else message


class FFprobeAdapter:
    """负责读取媒体基础信息的 ffprobe 适配器。"""

    def __init__(self, ffprobe_path: str | Path | None = "ffprobe") -> None:
        self.ffprobe_path = Path(ffprobe_path) if ffprobe_path is not None else None

    def resolve_executable(self) -> Path:
        """解析可执行文件路径，优先使用随包资源。"""

        if self.ffprobe_path is not None:
            if self.ffprobe_path.exists():
                return self.ffprobe_path
            if self.ffprobe_path.name not in {"ffprobe", "ffprobe.exe"}:
                raise FileNotFoundError(f"未找到 ffprobe 可执行文件: {self.ffprobe_path}")

        for candidate in self._bundle_candidates():
            if candidate.exists():
                return candidate

        fallback_name = self.ffprobe_path.name if self.ffprobe_path is not None else "ffprobe"
        fallback = shutil.which(fallback_name)
        if fallback:
            return Path(fallback)

        raise FileNotFoundError("未找到 ffprobe，可执行文件既不在随包目录也不在 PATH 中。")

    def _bundle_candidates(self) -> list[Path]:
        """返回应用内置的候选可执行文件路径。"""

        candidates = [Path(__file__).resolve().parents[2] / "resources" / "bin" / "ffmpeg" / "ffprobe.exe"]
        bundle_root = getattr(sys, "_MEIPASS", None)
        if bundle_root:
            candidates.insert(0, Path(bundle_root) / "resources" / "bin" / "ffmpeg" / "ffprobe.exe")
        return candidates

    def probe(self, source_path: Path) -> MediaProbeResultDTO:
        executable = self.resolve_executable()
        command = [
            str(executable),
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(source_path),
        ]

        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            # Windows 中文系统的默认编码通常是 `gbk`，而 `ffprobe` 的 JSON
            # 和错误输出可能包含 UTF-8 文件名。显式指定编码，避免 Python
            # 在线程读取子进程输出时因 UnicodeDecodeError 让导入任务失败。
            encoding="utf-8",
            errors="replace",
            check=False,
            # `ffprobe` 是控制台程序；桌面安装版在 Windows 上启动它时
            # 使用无窗口标志，避免探测视频时闪出黑色终端窗口。
            creationflags=(
                subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            ),
        )
        if completed.returncode != 0:
            raise FFprobeError(
                command=command,
                returncode=completed.returncode,
                stderr=completed.stderr or completed.stdout,
            )

        payload = json.loads(completed.stdout or "{}")
        return self._parse_payload(source_path=source_path, payload=payload)

    def _parse_payload(self, source_path: Path, payload: dict[str, object]) -> MediaProbeResultDTO:
        streams = list(payload.get("streams", []))
        format_info = dict(payload.get("format", {}))

        duration_ms = int(float(format_info.get("duration", 0)) * 1000)

        video_stream = None
        audio_streams: list[AudioStreamDTO] = []
        for stream in streams:
            if not isinstance(stream, dict):
                continue
            if stream.get("codec_type") == "video" and video_stream is None:
                video_stream = VideoStreamDTO(
                    codec_name=str(stream.get("codec_name", "")),
                    width=int(stream.get("width", 0)),
                    height=int(stream.get("height", 0)),
                )
            elif stream.get("codec_type") == "audio":
                tags = stream.get("tags")
                language = None
                if isinstance(tags, dict):
                    language_value = tags.get("language")
                    language = str(language_value) if language_value is not None else None
                audio_streams.append(
                    AudioStreamDTO(
                        codec_name=str(stream.get("codec_name", "")),
                        sample_rate=int(stream.get("sample_rate", 0)),
                        channels=int(stream.get("channels", 0)),
                        language=language,
                    )
                )

        return MediaProbeResultDTO(
            source_path=source_path,
            duration_ms=duration_ms,
            video_stream=video_stream,
            audio_streams=audio_streams,
        )
