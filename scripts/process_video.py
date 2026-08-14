"""无界面的 MVP 完整处理入口。

这个脚本把已经实现的四个核心用例串成用户可执行的最小主链路：
导入、识别、翻译和外挂字幕导出。脚本只负责参数和用例调用，
不会直接访问 `FFmpeg`、翻译 HTTP 接口或仓储实现。
"""

from __future__ import annotations

import argparse
from pathlib import Path

from app.bootstrap import bootstrap_application
from core.domain.enums import ExportMode
from core.dto.project_dto import CreateProjectInput
from core.dto.subtitle_dto import TranscribeVideoInput, TranslateSubtitlesInput
from core.dto.task_dto import ExportVideoInput


def build_parser() -> argparse.ArgumentParser:
    """创建完整处理流程的命令行参数解析器。"""

    parser = argparse.ArgumentParser(description="生成、翻译并导出视频字幕。")
    parser.add_argument("video", type=Path, help="待处理的本地视频路径。")
    parser.add_argument("--source-language", default="auto", help="源语言代码。")
    parser.add_argument("--target-language", default="zh-CN", help="目标语言代码。")
    parser.add_argument("--context", default=None, help="可选的作品或术语上下文。")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="导出视频路径；不传时使用项目级 exports 目录。",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """执行单视频 MVP 主链路，并输出最终产物路径。"""

    args = build_parser().parse_args(argv)
    source_video = args.video.resolve()
    if not source_video.is_file():
        raise FileNotFoundError(f"未找到待处理视频：{source_video}")

    context = bootstrap_application()
    task_service = context.container.create_task_service()

    # 第一步：导入视频并创建项目目录和文件指纹。
    created = task_service.create_project(
        CreateProjectInput(
            source_video=source_video,
            source_language=args.source_language,
            target_language=args.target_language,
            workspace_dir=context.workspace.root,
        )
    )

    # 第二步：本地抽取音频、识别并写出原文字幕。
    transcribed = task_service.transcribe_video(
        TranscribeVideoInput(project_id=created.project.project_id)
    )

    # 第三步：只把字幕文本和语言上下文交给云端翻译适配器。
    translated = task_service.translate_subtitles(
        TranslateSubtitlesInput(
            project_id=created.project.project_id,
            source_language=args.source_language,
            target_language=args.target_language,
            context=args.context,
        )
    )
    if translated.subtitle_path is None:
        raise RuntimeError("翻译完成后没有生成正式字幕文件。")

    # 第四步：默认导出视频副本和同名 `.srt` 旁车字幕。
    output_path = args.output
    if output_path is None:
        output_path = created.project.workspace_dir / "exports" / source_video.name
    output_path = output_path.resolve()
    exported = task_service.export_video(
        ExportVideoInput(
            project_id=created.project.project_id,
            source_video=source_video,
            subtitle_path=translated.subtitle_path,
            output_path=output_path,
            mode=ExportMode.SOFT_SUBTITLE,
        )
    )

    print(f"项目目录：{created.project.workspace_dir}")
    print(f"原文字幕：{transcribed.subtitle_path}")
    print(f"译文字幕：{translated.subtitle_path}")
    print(f"导出视频：{exported.export_record.output_path}")
    print(f"外挂字幕：{exported.export_record.subtitle_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
