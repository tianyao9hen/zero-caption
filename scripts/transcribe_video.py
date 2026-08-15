"""无界面的单视频识别入口。

这个脚本用于阶段 2 的真实链路验收，也方便开发者在 UI 接入前直接验证
“创建项目 -> 探测媒体 -> 抽取音频 -> 本地识别 -> 写出原文字幕”。
业务顺序仍由核心用例负责，脚本本身只解析参数并调用 `TaskService`。
"""

from __future__ import annotations

import argparse
from pathlib import Path

from app.bootstrap import bootstrap_application
from core.dto.project_dto import CreateProjectInput
from core.dto.subtitle_dto import TranscribeVideoInput


def build_parser() -> argparse.ArgumentParser:
    """创建命令行参数解析器。"""

    parser = argparse.ArgumentParser(description="为本地视频生成原文 SRT 字幕。")
    parser.add_argument("video", type=Path, help="待识别的本地视频路径。")
    parser.add_argument(
        "--source-language",
        default="auto",
        help="源语言代码；默认 auto 表示让识别引擎自动检测。",
    )
    parser.add_argument(
        "--target-language",
        default="zh-CN",
        help="项目目标语言；阶段 2 只记录该值，不会发起翻译。",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """执行单视频本地识别，并在终端输出产物路径。

    参数：
        argv：可选的命令行参数列表。测试可传入自定义列表，
            普通运行时不传则由 `argparse` 读取系统命令行。

    返回：
        成功时返回 0。输入文件不存在或识别失败时会抛出明确异常，
        由终端和应用日志共同保留诊断信息。
    """

    args = build_parser().parse_args(argv)
    source_video = args.video.resolve()
    if not source_video.is_file():
        raise FileNotFoundError(f"未找到待识别视频：{source_video}")

    # 第一步：完成配置、工作区、日志和依赖装配。
    # 这里复用桌面应用相同的启动装配，避免命令行入口形成第二套实现。
    context = bootstrap_application()
    task_service = context.container.create_task_service()

    # 第二步：创建项目。项目目录和文件指纹由核心用例通过端口完成。
    create_result = task_service.create_project(
        CreateProjectInput(
            source_video=source_video,
            source_language=args.source_language,
            target_language=args.target_language,
            workspace_dir=context.workspace.root,
        )
    )

    # 第三步：只把项目编号交给识别用例。
    # 源视频、工作目录和语言都来自项目记录，调用方不需要重复拼路径。
    result = task_service.transcribe_video(
        TranscribeVideoInput(project_id=create_result.project.project_id)
    )

    print(f"项目目录：{create_result.project.workspace_dir}")
    print(f"识别片段：{len(result.source_segments)}")
    print(f"运行方式：{result.runtime_message or '识别引擎未提供运行摘要。'}")
    print(f"原文字幕：{result.subtitle_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
