"""大模型测试用例和 Qt 后台执行器的单元测试。"""

from __future__ import annotations

import threading

import pytest
from PySide6.QtWidgets import QApplication

from config.settings import TranslationSettings
from core.usecases.translation_model_test import TranslationModelTest
from ui.viewmodels.translation_test_runner import TranslationTestRunner


class RecordingModelTester:
    """记录提示词并返回固定文本，避免测试访问真实网络。"""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def test_prompt(self, user_prompt: str) -> str:
        """记录核心用例传入的用户提示词。"""

        self.prompts.append(user_prompt)
        return "测试响应"


def test_translation_model_usecase_validates_and_forwards_prompt() -> None:
    """核心测试用例应清理输入空白，并拒绝空用户提示词。"""

    tester = RecordingModelTester()
    usecase = TranslationModelTest(tester)

    assert usecase.execute("  请测试连接  ") == "测试响应"
    assert tester.prompts == ["请测试连接"]
    with pytest.raises(ValueError, match="用户提示词"):
        usecase.execute("   ")


def test_translation_test_runner_executes_tester_outside_ui_thread(monkeypatch) -> None:
    """耗时模型测试必须在 Qt 工作线程执行，并把成功结果发回界面。"""

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    ui_thread_id = threading.get_ident()
    worker_thread_ids: list[int] = []
    results: list[str] = []

    def tester(settings: TranslationSettings, prompt: str) -> str:
        worker_thread_ids.append(threading.get_ident())
        return f"{settings.model}:{prompt}"

    runner = TranslationTestRunner(
        tester,
        TranslationSettings(model="test-model"),
        "测试提示词",
    )
    runner.succeeded.connect(results.append)
    runner.start()

    assert runner.wait(2_000) is True
    app.processEvents()
    assert worker_thread_ids and worker_thread_ids[0] != ui_thread_id
    assert results == ["test-model:测试提示词"]
    runner.deleteLater()
    app.processEvents()


def test_translation_test_runner_reports_failure(monkeypatch) -> None:
    """后台测试异常应转换成失败信号，不能让 Qt 线程静默崩溃。"""

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    errors: list[str] = []

    def tester(settings: TranslationSettings, prompt: str) -> str:
        raise RuntimeError("模拟服务失败")

    runner = TranslationTestRunner(tester, TranslationSettings(), "测试")
    runner.failed.connect(errors.append)
    runner.start()

    assert runner.wait(2_000) is True
    app.processEvents()
    assert errors == ["模拟服务失败"]
    runner.deleteLater()
    app.processEvents()
