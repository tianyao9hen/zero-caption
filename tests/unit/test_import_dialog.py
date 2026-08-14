"""导入对话框的参数转换测试，保护 UI 与核心 DTO 的边界。"""

from pathlib import Path

from PySide6.QtWidgets import QApplication

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
    dialog.deleteLater()
    app.processEvents()
