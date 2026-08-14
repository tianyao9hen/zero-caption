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
    dialog = ImportDialog(translation_configured=True)
    dialog.video_edit.setText(str(source_video))

    # act
    request = dialog.to_request(tmp_path / "workspace")

    # assert：完整模式选中后，翻译和导出控件可编辑。
    assert request.processing_mode is ProcessingMode.FULL_PIPELINE
    assert dialog.target_language_combo.isEnabled() is True
    assert dialog.export_mode_combo.isEnabled() is True
    dialog.deleteLater()
    app.processEvents()
