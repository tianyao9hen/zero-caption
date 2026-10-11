"""已有项目重新导出用例。

本模块位于核心层，负责从结构化字幕重建正式字幕文件，再调用现有视频
导出用例。它不依赖 Qt、SQLite 或具体 `FFmpeg` 实现。

它同时承担两种业务动作：

1. 用户点击“下载成品”：优先复用项目目录里已经烧录好的成品，直接复制；
   成品缺失或译文已经改动时才重新烧录。
2. 任务创建流程的后台预生成：把成品烧录到项目自己的 `exports/` 目录，
   让用户稍后下载时不需要等待几十分钟的重新编码。
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re

from core.domain.entities import Project
from core.domain.enums import ExportMode
from core.dto.subtitle_dto import SubtitleSegmentDTO
from core.dto.task_dto import (
    ExportVideoInput,
    ExportVideoResult,
    ReexportProjectInput,
)
from core.ports.repository import ProjectRepository, SubtitleRepository
from core.ports.subtitle import SubtitleWriter
from core.usecases.export_video import ExportVideo

# 后台预生成的成品与用户下载成品放在同一个 `exports/` 目录，
# 通过文件名后缀区分，避免两种产物互相覆盖。
_PREPARED_PRODUCT_SUFFIX = "-烧录成品"


@dataclass(slots=True)
class ReexportProject:
    """使用项目当前保存的完整译文重新生成下载成品。

    单句编辑会先更新结构化字幕仓储。重新导出时从仓储重新写出 `SRT`，
    可以确保下载结果采用最新译文，而不是误用上一次导出时复制的旧字幕。

    烧录模式下，它会先检查项目目录里有没有针对当前译文生成的成品：
    有就直接交付，没有才真正调用 `FFmpeg`。这条复用路径让用户点击下载后
    几乎立刻拿到文件，也让创建任务时的自动预生成真正有意义。
    """

    project_repository: ProjectRepository
    subtitle_repository: SubtitleRepository
    subtitle_writer: SubtitleWriter
    export_video: ExportVideo

    def execute(self, request: ReexportProjectInput) -> ExportVideoResult:
        """校验完整译文、重写字幕文件并执行一次视频导出。

        副作用：
            会重写项目级译文 `SRT`、更新项目保存的导出参数，并创建新的
            任务与导出记录。原始视频和音频始终留在本地。
        """

        project = self.project_repository.get_by_id(request.project_id)
        if project is None:
            raise ValueError(f"未找到项目：{request.project_id}")

        # 第一步：同时读取原文和译文，用稳定的字幕编号检查译文是否完整。
        # 只检查数量并不够，因为历史异常数据可能出现重复或错位编号。
        source_segments = self.subtitle_repository.get_source_segments(
            project.project_id
        )
        translated_segments = self.subtitle_repository.get_translated_segments(
            project.project_id,
            project.target_language,
        )
        translated_by_id = {
            segment.segment_id: segment for segment in translated_segments
        }
        if not source_segments or any(
            source.segment_id not in translated_by_id
            for source in source_segments
        ):
            raise ValueError("重新导出前必须先生成完整译文字幕。")
        ordered_segments = [
            translated_by_id[source.segment_id] for source in source_segments
        ]

        # 第二步：从结构化数据重写正式字幕，确保刚保存的人工修订会进入成品。
        language_name = self._safe_language_name(project.target_language)
        subtitle_path = (
            project.workspace_dir
            / "subtitles"
            / f"translated-{language_name}.srt"
        )
        subtitle_path = self.subtitle_writer.write_file(
            ordered_segments,
            subtitle_path,
        )

        # 第三步：计算本次译文字幕的指纹。它是判断已有成品是否还新鲜的
        # 唯一依据：用户只要改动过任何一条译文，指纹就会变化。
        translation_signature = self.translation_signature(ordered_segments)

        # 预生成前保留用户上次选择的下载目录。`ExportVideo` 成功后会把
        # `output_path` 更新为本次实际落盘路径，而预生成的目标是项目内部
        # 目录，不应该污染这个用户可见字段。
        previous_output_path = project.output_path

        if request.prepare_project_product:
            return self._produce_product(
                project=project,
                request=request,
                subtitle_path=subtitle_path,
                output_path=self.prepared_product_path(project),
                prepared_source_path=None,
                task_type="prepare_product",
                translation_signature=translation_signature,
                previous_output_path=previous_output_path,
            )

        # 第四步：优先采用本次显式路径，其次按当前模式复用项目上次路径，
        # 最后回退到项目 `exports/`。模式切换时要修正扩展名，避免之前下载
        # 外挂字幕留下的 `.srt` 被误当成烧录视频输出路径。
        output_path = self._resolve_output_path(project, request)
        prepared_source_path = self._resolve_reusable_product(
            project,
            request.mode,
            translation_signature,
        )

        if prepared_source_path is None and request.mode is ExportMode.BURN_IN:
            # 没有现成成品可用。这里先在工作区烧录最新版：既让本次下载之后
            # 还能瞬间重下，也避免用户每改一条字幕就重新等待几十分钟。
            self._produce_product(
                project=project,
                request=request,
                subtitle_path=subtitle_path,
                output_path=self.prepared_product_path(project),
                prepared_source_path=None,
                task_type="prepare_product",
                translation_signature=translation_signature,
                previous_output_path=previous_output_path,
            )
            refreshed_project = self.project_repository.get_by_id(
                project.project_id
            )
            if refreshed_project is not None:
                project = refreshed_project
            prepared_source_path = self._resolve_reusable_product(
                project,
                request.mode,
                translation_signature,
            )

        return self._produce_product(
            project=project,
            request=request,
            subtitle_path=subtitle_path,
            output_path=output_path,
            prepared_source_path=prepared_source_path,
            task_type="export_video",
            translation_signature=translation_signature,
            previous_output_path=previous_output_path,
        )

    def _produce_product(
        self,
        *,
        project: Project,
        request: ReexportProjectInput,
        subtitle_path: Path,
        output_path: Path,
        prepared_source_path: Path | None,
        task_type: str,
        translation_signature: str,
        previous_output_path: Path | None,
    ) -> ExportVideoResult:
        """执行一次真正的导出，并把结果登记为项目状态。

        参数：
            output_path：本次成品的落盘路径。
            prepared_source_path：非空时走复制通道，不重新编码。
            task_type：`prepare_product` 会额外登记项目内成品，
            `export_video` 只更新用户可见下载路径。
            previous_output_path：用户上次选择的下载目录，
            预生成结束后要写回这个字段。
        """

        project.export_mode = request.mode
        project.output_path = output_path
        project.touch()
        self.project_repository.save(project)

        try:
            result = self.export_video.execute(
                ExportVideoInput(
                    project_id=project.project_id,
                    source_video=project.source_video,
                    subtitle_path=subtitle_path,
                    output_path=output_path,
                    mode=request.mode,
                    prepared_source_path=prepared_source_path,
                    task_type=task_type,
                )
            )
        except Exception:
            if task_type == "prepare_product":
                # 预生成失败不应该让用户上次选择的下载目录被内部路径污染。
                self._restore_output_path(project, previous_output_path)
            raise

        if task_type == "prepare_product":
            self._record_prepared_product(
                project,
                prepared_output_path=Path(result.export_record.output_path),
                translation_signature=translation_signature,
                previous_output_path=previous_output_path,
            )
        return result

    def has_prepared_product(
        self,
        project_id: str,
        mode: ExportMode = ExportMode.BURN_IN,
    ) -> bool:
        """返回项目是否已经有一份仍然新鲜的预生成成品。

        参数：
            project_id：项目编号。
            mode：导出模式；只有烧录模式会预生成视频成品。

        返回：
            `True` 表示可以直接复制交付，`False` 表示需要重新生成。

        这个方法只做只读判断，供主链路在开始昂贵工作前先问一次，
        避免每次都重新烧录同一份视频。
        """

        project = self.project_repository.get_by_id(project_id)
        if project is None:
            return False
        ordered_segments = self._ordered_translated_segments(project)
        if not ordered_segments:
            return False
        signature = self.translation_signature(ordered_segments)
        return self._resolve_reusable_product(project, mode, signature) is not None

    @staticmethod
    def prepared_product_path(project: Project) -> Path:
        """返回项目目录内预生成成品的固定落盘路径。"""

        suffix = project.source_video.suffix or ".mp4"
        return (
            project.workspace_dir
            / "exports"
            / f"{project.source_video.stem}{_PREPARED_PRODUCT_SUFFIX}{suffix}"
        )

    @staticmethod
    def translation_signature(segments: list[SubtitleSegmentDTO]) -> str:
        """计算一段译文的内容指纹，用于判断已有成品是否过期。

        这里使用标准库摘要，不需要读取文件，也不依赖任何基础设施端口。
        只要编号、时间轴或文本有任何变化，结果都会不同。
        """

        payload = "\n".join(
            f"{segment.segment_id}|{segment.start_ms}|{segment.end_ms}|"
            f"{segment.text}"
            for segment in segments
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _ordered_translated_segments(
        self,
        project: Project,
    ) -> list[SubtitleSegmentDTO]:
        """按原文顺序取出译文；译文尚未齐备时返回空列表。"""

        source_segments = self.subtitle_repository.get_source_segments(
            project.project_id
        )
        translated_by_id = {
            segment.segment_id: segment
            for segment in self.subtitle_repository.get_translated_segments(
                project.project_id,
                project.target_language,
            )
        }
        ordered_segments = []
        for source in source_segments:
            translated = translated_by_id.get(source.segment_id)
            if translated is None:
                return []
            ordered_segments.append(translated)
        return ordered_segments

    def _resolve_reusable_product(
        self,
        project: Project,
        mode: ExportMode,
        translation_signature: str,
    ) -> Path | None:
        """返回可直接交付的现成成品路径，不能复用时返回 `None`。

        三个条件必须同时满足，缺少任何一个都要回到正常烧录：

        1. 本次导出模式确实是烧录；外挂字幕只需要复制 `.srt`，没有重编码成本。
        2. 项目记录里存在预生成成品，并且该文件此刻仍然在项目目录中。
        3. 预生成时使用的译文和当前译文完全一致，用户没有在事后改过字幕。
        """

        if mode is not ExportMode.BURN_IN:
            return None
        prepared_path = project.prepared_output_path
        if prepared_path is None or not prepared_path.is_file():
            return None
        if project.prepared_translation_signature != translation_signature:
            return None
        return prepared_path

    def _record_prepared_product(
        self,
        project: Project,
        prepared_output_path: Path,
        translation_signature: str,
        previous_output_path: Path | None,
    ) -> None:
        """把预生成结果登记到项目，并恢复用户可见下载路径。

        `ExportVideo` 已经把 `output_path` 改成了本次实际落盘路径。预算内
        产物属于内部文件，因此这里要把它换到专用字段，并把用户上次选择的
        下载目录写回去，避免下载对话框默认跳进项目缓存目录。
        """

        stored_project = self.project_repository.get_by_id(project.project_id)
        if stored_project is None:  # pragma: no cover - 项目刚写入，正常必然存在
            return
        stored_project.prepared_output_path = prepared_output_path
        stored_project.prepared_translation_signature = translation_signature
        stored_project.output_path = previous_output_path
        stored_project.touch()
        self.project_repository.save(stored_project)

    def _restore_output_path(
        self,
        project: Project,
        previous_output_path: Path | None,
    ) -> None:
        """预生成失败后恢复用户可见下载路径，避免内部路径泄漏到界面。"""

        stored_project = self.project_repository.get_by_id(project.project_id)
        if stored_project is None:  # pragma: no cover - 项目必然已经存在
            return
        stored_project.output_path = previous_output_path
        stored_project.touch()
        self.project_repository.save(stored_project)

    @staticmethod
    def _safe_language_name(language: str) -> str:
        """把语言代码转换成不会改变目录层级的文件名片段。"""

        safe_name = re.sub(r"[^0-9A-Za-z_-]+", "_", language).strip("_")
        return safe_name or "translated"

    @staticmethod
    def _resolve_output_path(
        project,
        request: ReexportProjectInput,
    ):
        """按导出模式选择一个不会混淆视频和字幕的默认路径。"""

        if request.output_path is not None:
            return request.output_path

        previous_path = project.output_path
        if previous_path is not None:
            if request.mode is ExportMode.SOFT_SUBTITLE:
                return previous_path.with_suffix(".srt")
            if previous_path.suffix.lower() == ".srt":
                return previous_path.with_suffix(
                    project.source_video.suffix or ".mp4"
                )
            return previous_path

        if request.mode is ExportMode.SOFT_SUBTITLE:
            return (
                project.workspace_dir
                / "exports"
                / f"{project.source_video.stem}-字幕.srt"
            )
        return project.workspace_dir / "exports" / project.source_video.name
