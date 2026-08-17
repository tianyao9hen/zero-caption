"""项目状态页面。

页面属于 UI 层，只展示核心服务返回的项目结果和路径信息。
它不创建仓储、不访问媒体工具，也不保存业务状态副本。
"""

from __future__ import annotations

from pathlib import Path

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
        self.audio_label = QLabel("-")
        self.subtitle_label = QLabel("-")
        self.output_label = QLabel("-")
        for label in [
            self.project_id_label,
            self.source_label,
            self.status_label,
            self.workspace_label,
            self.audio_label,
            self.subtitle_label,
            self.output_label,
        ]:
            label.setTextInteractionFlags(
                label.textInteractionFlags() | Qt.TextInteractionFlag.TextSelectableByMouse
            )

        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(6)
        form.addRow("项目编号", self.project_id_label)
        form.addRow("源视频", self.source_label)
        form.addRow("项目状态", self.status_label)
        form.addRow("工作区", self.workspace_label)
        form.addRow("识别音频", self.audio_label)
        form.addRow("字幕文件", self.subtitle_label)
        form.addRow("最近下载", self.output_label)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        layout.addLayout(form)
        layout.addStretch(1)

    def show_result(self, result: ProcessVideoResult) -> None:
        """展示本次处理结果中的项目和实际生成产物。"""

        project = result.final_project
        self.project_id_label.setText(project.project_id)
        self.source_label.setText(str(project.source_video))
        self.status_label.setText(project.status.value)
        self.workspace_label.setText(str(project.workspace_dir))
        self.audio_label.setText(str(result.transcription.audio_path or "-"))
        self.subtitle_label.setText(str(result.subtitle_path or "-"))
        if result.export is None:
            self.output_label.setText("等待用户下载")
        else:
            self.output_label.setText(str(result.export.export_record.output_path))

    def show_workspace_root(self, workspace_root: str | Path) -> None:
        """工作区切换后显示新的根目录，避免页面继续展示旧地址。"""

        self.workspace_label.setText(str(workspace_root))
