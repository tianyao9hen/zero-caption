"""项目状态页面。

页面属于 UI 层，只展示核心服务返回的项目结果和路径信息。
它不创建仓储、不访问媒体工具，也不保存业务状态副本。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QLabel, QVBoxLayout, QWidget

from core.dto.pipeline_dto import ProcessVideoResult
from core.services.task_service import TaskService
from infrastructure.storage.workspace import WorkspaceManager


class ProjectsPage(QWidget):
    """显示最近一次项目处理结果。"""

    def __init__(self, workspace: WorkspaceManager, task_service: TaskService) -> None:
        super().__init__()
        self.project_id_label = QLabel("暂无项目")
        self.source_label = QLabel("-")
        self.status_label = QLabel("-")
        self.workspace_label = QLabel(str(workspace.root))
        self.output_label = QLabel("-")
        for label in [
            self.project_id_label,
            self.source_label,
            self.status_label,
            self.workspace_label,
            self.output_label,
        ]:
            label.setTextInteractionFlags(
                label.textInteractionFlags() | Qt.TextInteractionFlag.TextSelectableByMouse
            )

        form = QFormLayout()
        form.addRow("项目编号", self.project_id_label)
        form.addRow("源视频", self.source_label)
        form.addRow("项目状态", self.status_label)
        form.addRow("工作区", self.workspace_label)
        form.addRow("最近导出", self.output_label)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addStretch(1)

    def show_result(self, result: ProcessVideoResult) -> None:
        """展示完整处理结果中的项目和最终导出路径。"""

        project = result.export.project
        self.project_id_label.setText(project.project_id)
        self.source_label.setText(str(project.source_video))
        self.status_label.setText(project.status.value)
        self.workspace_label.setText(str(project.workspace_dir))
        self.output_label.setText(str(result.export.export_record.output_path))
