"""任务页面逐句翻译展示的单元测试。"""

from PySide6.QtWidgets import QApplication

from core.dto.subtitle_dto import TranslationProgressDTO
from core.services.task_service import TaskService
from ui.pages.tasks_page import TasksPage


def test_tasks_page_appends_translation_progress_in_real_time(monkeypatch) -> None:
    """每条翻译事件应追加原文和译文，并更新当前完成数量。"""

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    page = TasksPage(TaskService())
    progress = TranslationProgressDTO(
        task_id="task-1",
        current_index=1,
        total_segments=2,
        source_text="hello",
        translated_text="你好",
    )

    page.update_translation_progress(progress)
    app.processEvents()

    preview = page.translation_preview.toPlainText()
    assert page.translation_count_label.text() == "已完成 1/2 条"
    assert "原文：hello" in preview
    assert "译文：你好" in preview
    page.deleteLater()
    app.processEvents()
