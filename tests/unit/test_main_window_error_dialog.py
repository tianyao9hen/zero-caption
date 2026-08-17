"""主窗口后台失败对话框的单元测试。

这个测试只验证错误摘要和完整诊断文本如何交给界面控件，
不启动真实翻译服务，也不弹出会阻塞自动化测试的系统窗口。
"""

from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtCore import Qt

from ui.windows.main_window import MainWindow


class RecordingMessageBox:
    """记录主窗口写入消息框的属性，代替真实阻塞式 Qt 对话框。"""

    class Icon:
        """提供主窗口调用所需的最小图标枚举替身。"""

        Critical = "critical"

    class StandardButton:
        """提供主窗口调用所需的最小按钮枚举替身。"""

        Ok = "ok"

    created: list["RecordingMessageBox"] = []

    def __init__(self, parent) -> None:
        """保存父对象，并登记本次创建的消息框。"""

        self.parent = parent
        self.icon = None
        self.title = ""
        self.text_format = None
        self.text = ""
        self.buttons = None
        self.executed = False
        self.created.append(self)

    def setIcon(self, icon) -> None:
        """记录错误图标。"""

        self.icon = icon

    def setWindowTitle(self, title: str) -> None:
        """记录窗口标题。"""

        self.title = title

    def setTextFormat(self, text_format) -> None:
        """记录文本格式，确保模型返回不会被当成富文本。"""

        self.text_format = text_format

    def setText(self, text: str) -> None:
        """记录完整错误正文。"""

        self.text = text

    def setStandardButtons(self, buttons) -> None:
        """记录消息框按钮。"""

        self.buttons = buttons

    def exec(self) -> None:
        """模拟用户关闭对话框，不进入真实 Qt 事件循环。"""

        self.executed = True


def test_pipeline_failure_dialog_shows_raw_model_response_as_plain_text(
    monkeypatch,
) -> None:
    """后台翻译格式错误应在弹窗展示完整原始返回，状态栏只保留摘要。"""

    # arrange：用简单替身提供主窗口方法依赖的页面、状态栏和消息框接口。
    RecordingMessageBox.created.clear()
    refreshed: list[bool] = []
    status_messages: list[str] = []
    fake_window = SimpleNamespace(
        tasks_page=SimpleNamespace(refresh_history=lambda: refreshed.append(True)),
        status_widget=SimpleNamespace(show_message=status_messages.append),
        _pending_task_deletions=set(),
    )
    monkeypatch.setattr(
        "ui.windows.main_window.QMessageBox",
        RecordingMessageBox,
    )
    message = (
        "翻译响应中没有有效的 translations 字幕列表。\n\n"
        "大模型原始返回：\n<b>模型返回的说明文字</b>"
    )

    # act：直接调用界面层失败处理方法，避免构造完整应用容器。
    MainWindow._handle_pipeline_failure(fake_window, message)

    # assert：状态栏保持简短，弹窗则以纯文本保留全部模型正文。
    assert refreshed == [True]
    assert status_messages == [
        "处理失败：翻译响应中没有有效的 translations 字幕列表。"
    ]
    dialog = RecordingMessageBox.created[0]
    assert dialog.title == "处理失败"
    assert dialog.text_format is Qt.TextFormat.PlainText
    assert dialog.text == message
    assert dialog.executed is True
