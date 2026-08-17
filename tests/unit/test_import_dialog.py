"""导入对话框的参数转换测试，保护 UI 与核心 DTO 的边界。"""

from pathlib import Path

from PySide6.QtWidgets import QApplication

from core.domain.enums import ProcessingMode
from ui.dialogs.import_dialog import ImportDialog


def test_import_dialog_to_request_keeps_user_choices(tmp_path) -> None:
    """表单选择应转换为完整的 `ProcessVideoInput`，空上下文归一为 None。"""

    # arrange：Qt 控件必须绑定到进程内唯一的 QApplication。
    app = QApplication.instance() or QApplication([])
    source_video = tmp_path / "clip.mp4"
    source_video.write_bytes(b"video")
    dialog = ImportDialog(
        default_source_language="en",
        default_target_language="ja",
        default_output_directory=tmp_path / "chosen-results",
    )
    dialog.video_edit.setText(str(source_video))
    dialog.source_language_combo.setCurrentText("en")
    dialog.target_language_combo.setCurrentText("ja")
    dialog.context_edit.setText("science fiction")

    # act：读取对话框当前表单并转换 DTO。
    request = dialog.to_request(tmp_path / "workspace")

    # assert：路径、语言、上下文和默认输出路径语义均正确。
    assert request.source_video == Path(source_video)
    assert request.source_language == "en"
    assert request.target_language == "ja"
    assert request.context == "science fiction"
    assert request.workspace_dir == tmp_path / "workspace"
    assert request.output_path == tmp_path / "chosen-results" / "clip.srt"
    assert request.processing_mode is ProcessingMode.TRANSCRIBE_ONLY
    assert dialog.target_language_combo.isEnabled() is False
    dialog.deleteLater()
    app.processEvents()


def test_import_dialog_defaults_to_full_pipeline_when_translation_is_configured(
    tmp_path,
) -> None:
    """检测到完整大模型配置时，导入表单应继续沿用完整处理流程。"""

    # arrange：这个测试只验证表单默认值，不会真正访问大模型接口。
    app = QApplication.instance() or QApplication([])
    source_video = tmp_path / "clip.mp4"
    source_video.write_bytes(b"video")
    dialog = ImportDialog(
        translation_configured=True,
        default_output_directory=tmp_path / "chosen-results",
    )
    dialog.video_edit.setText(str(source_video))

    # act
    request = dialog.to_request(tmp_path / "workspace")

    # assert：完整模式不预先选择外部目录，下载位置留到翻译完成后决定。
    assert request.processing_mode is ProcessingMode.FULL_PIPELINE
    assert request.output_path is None
    assert dialog.target_language_combo.isEnabled() is True
    assert dialog.export_mode_combo.isEnabled() is True
    assert dialog.output_directory_widget.isHidden() is True
    assert "下载成品" in dialog.output_preview_label.text()
    dialog.deleteLater()
    app.processEvents()


def test_import_dialog_browses_result_directory_and_updates_preview(
    tmp_path,
    monkeypatch,
) -> None:
    """用户选择成果目录后，表单应实时展示最终字幕保存路径。"""

    app = QApplication.instance() or QApplication([])
    source_video = tmp_path / "course.mp4"
    source_video.write_bytes(b"video")
    selected_directory = tmp_path / "my results"
    monkeypatch.setattr(
        "ui.dialogs.import_dialog.QFileDialog.getExistingDirectory",
        lambda *_args, **_kwargs: str(selected_directory),
    )
    dialog = ImportDialog()
    dialog.video_edit.setText(str(source_video))

    dialog.output_directory_button.click()
    app.processEvents()

    assert dialog.output_directory_edit.text() == str(selected_directory)
    assert dialog.output_path() == selected_directory / "course.srt"
    assert str(selected_directory / "course.srt") in dialog.output_preview_label.text()
    dialog.deleteLater()
    app.processEvents()


def test_import_dialog_explains_task_creation_and_asr_runtime() -> None:
    """创建任务表单应明确展示识别运行参数和提交动作。"""

    app = QApplication.instance() or QApplication([])
    dialog = ImportDialog(asr_runtime_summary="medium / GPU / float16")

    assert dialog.windowTitle() == "创建视频处理任务"
    assert dialog.asr_runtime_label.text() == "medium / GPU / float16"
    assert "后台" in dialog.processing_hint_label.text()

    dialog.deleteLater()
    app.processEvents()
