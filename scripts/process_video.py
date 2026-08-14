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
from core.dto.pipeline_dto import ProcessVideoInput


def build_parser() -> argparse.ArgumentParser:
    """创建完整处理流程的命令行参数解析器。"""

    parser = argparse.ArgumentParser(description="生成、翻译并导出视频字幕。")
    parser.add_argument("video", type=Path, help="待处理的本地视频路径。")
    parser.add_argument("--source-language", default="auto", help="源语言代码。")
    parser.add_argument("--target-language", default="zh-CN", help="目标语言代码。")
    parser.add_argument("--context", default=None, help="可选的作品或术语上下文。")
    parser.add_argument(
        "--export-mode",
        choices=[mode.value for mode in ExportMode],
        default=ExportMode.SOFT_SUBTITLE.value,
        help="导出模式：外挂字幕或烧录字幕。",
    )
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

    # 完整业务顺序由核心服务维护，脚本不重复编排四个用例。
    # 这样桌面 UI 和命令行入口会共享同一条主链路。
    result = task_service.process_video(
        ProcessVideoInput(
            source_video=source_video,
            source_language=args.source_language,
            target_language=args.target_language,
            workspace_dir=context.workspace.root,
            context=args.context,
            output_path=args.output.resolve() if args.output is not None else None,
            export_mode=ExportMode(args.export_mode),
        )
    )

    print(f"项目目录：{result.project.project.workspace_dir}")
    print(f"原文字幕：{result.transcription.subtitle_path}")
    print(f"译文字幕：{result.translation.subtitle_path}")
    print(f"导出视频：{result.export.export_record.output_path}")
    print(f"外挂字幕：{result.export.export_record.subtitle_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
