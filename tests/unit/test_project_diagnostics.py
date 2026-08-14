"""项目日志和诊断包测试，保护隐私边界和可诊断产物。"""

from zipfile import ZipFile

from infrastructure.logging.diagnostic_bundle import DiagnosticBundle
from infrastructure.logging.project_logger import ProjectLogger


def test_project_logger_and_diagnostic_bundle_exclude_media(tmp_path) -> None:
    """诊断包应包含日志和字幕，但不能打包原始视频。"""

    project_dir = tmp_path / "project"
    (project_dir / "logs").mkdir(parents=True)
    (project_dir / "subtitles").mkdir()
    (project_dir / "source").mkdir()
    (project_dir / "source" / "video.mp4").write_bytes(b"private")
    (project_dir / "subtitles" / "source.srt").write_text("字幕", encoding="utf-8")
    logger = ProjectLogger(project_dir)
    logger.info("识别完成", task_id="task-1")
    bundle_path = DiagnosticBundle(project_dir).create(tmp_path / "diagnostic.zip")

    with ZipFile(bundle_path) as archive:
        names = archive.namelist()
    assert "logs/project.jsonl" in names
    assert "subtitles/source.srt" in names
    assert all("video.mp4" not in name for name in names)
