"""项目诊断包生成器。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import zipfile


@dataclass(slots=True)
class DiagnosticBundle:
    """把项目日志、字幕和数据库摘要打包为可分享的 ZIP 文件。"""

    project_dir: Path

    def create(self, output_path: Path) -> Path:
        """创建诊断包；不存在的可选文件会被自动跳过。"""

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in self._files_to_include():
                if path.is_file():
                    archive.write(path, path.relative_to(self.project_dir))
        return output_path

    def _files_to_include(self) -> list[Path]:
        """返回不包含原始视频和音频的诊断文件清单。"""

        candidates = [
            self.project_dir / "logs" / "project.jsonl",
            self.project_dir / "zero_caption.sqlite3",
        ]
        candidates.extend((self.project_dir / "subtitles").glob("*.srt"))
        candidates.extend((self.project_dir / "subtitles").glob("*.ass"))
        return candidates
