"""现成成品复制导出适配器测试。

它保护下载路径上的两件事：项目目录里的预生成成品可以被安全复制出去，
以及成品一旦丢失就要立刻报错让上层回退到正常烧录，而不是假装成功。
"""

from __future__ import annotations

from core.domain.enums import ExportMode
from core.dto.task_dto import ExportVideoInput
import pytest

from infrastructure.export.prepared_video_exporter import PreparedVideoExporter


def _request(tmp_path, prepared_path=None) -> ExportVideoInput:
    """构造一个携带预生成成品路径的导出请求。"""

    return ExportVideoInput(
        project_id="project-1",
        source_video=tmp_path / "source.mp4",
        subtitle_path=tmp_path / "translated.srt",
        output_path=tmp_path / "downloads" / "movie.mp4",
        mode=ExportMode.BURN_IN,
        prepared_source_path=prepared_path,
    )


def test_prepared_video_exporter_copies_product_to_download_directory(
    tmp_path,
) -> None:
    """已有成品时应复制到用户目录，且不动原文件。"""

    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"source video")
    prepared_path = tmp_path / "project" / "exports" / "movie-烧录成品.mp4"
    prepared_path.parent.mkdir(parents=True)
    prepared_path.write_bytes(b"burned video")

    record = PreparedVideoExporter().export(_request(tmp_path, prepared_path))

    expected_output = tmp_path / "downloads" / "movie.mp4"
    assert expected_output.read_bytes() == b"burned video"
    assert record.output_path == expected_output
    assert record.mode is ExportMode.BURN_IN
    # 预生成成品仍然留在任务目录里，后续还能继续下载。
    assert prepared_path.is_file()
    # 复制过程中产生的临时文件必须清理干净。
    assert [path.name for path in (tmp_path / "downloads").iterdir()] == [
        "movie.mp4"
    ]


def test_prepared_video_exporter_rejects_missing_product(tmp_path) -> None:
    """预生成成品不存在时应报错，交给上层回退到重新烧录。"""

    missing_path = tmp_path / "project" / "exports" / "movie-烧录成品.mp4"

    with pytest.raises(FileNotFoundError):
        PreparedVideoExporter().export(_request(tmp_path, missing_path))

    assert (tmp_path / "downloads" / "movie.mp4").exists() is False


def test_prepared_video_exporter_requires_prepared_path(tmp_path) -> None:
    """没有提供预生成路径时，这个导出器不能被调用。"""

    (tmp_path / "project" / "exports").mkdir(parents=True)
    prepared_path = tmp_path / "project" / "exports" / "movie-烧录成品.mp4"
    prepared_path.write_bytes(b"burned video")

    with pytest.raises(ValueError):
        PreparedVideoExporter().export(_request(tmp_path))
