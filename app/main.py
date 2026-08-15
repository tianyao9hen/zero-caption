"""桌面应用入口模块。

这个文件刻意保持很小，只负责创建 `QApplication` 对象、完成应用启动装配，
以及显示主窗口。较重的初始化逻辑集中放在 `app.bootstrap` 中，方便初学者
顺着单一入口阅读启动流程。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
import tempfile
import wave

from PySide6.QtWidgets import QApplication

from app.bootstrap import bootstrap_application, build_runtime_report
from core.ports.asr import AsrRuntimeReporter, AsrRuntimeVerifier


def main(argv: list[str] | None = None) -> int:
    """启动桌面应用，或执行发布包自检并返回退出码。"""

    _ensure_standard_streams()
    arguments = list(argv if argv is not None else sys.argv[1:])
    if "--self-test-report" in arguments:
        index = arguments.index("--self-test-report")
        if index + 1 >= len(arguments):
            return 2
        report_path = Path(arguments[index + 1])
        verify_asr_load = "--verify-asr-load" in arguments
        return _run_self_test(report_path, verify_asr_load=verify_asr_load)

    # `QApplication` 是桌面界面程序的根对象。
    # 几乎所有界面控件都依赖它，所以必须最先创建。
    app = QApplication(sys.argv)
    app.setApplicationName("Zero Caption")
    app.setOrganizationName("zero-caption")

    # bootstrap_application 会在一个地方完成配置、日志、工作区目录
    # 和依赖容器的组装，避免这些启动细节散落在入口文件里。
    context = bootstrap_application()
    window = context.container.create_main_window()
    window.show()

    # `app.exec()` 会进入事件循环。
    # 从这里开始，按钮点击等用户操作都会通过界面框架的事件和信号机制分发。
    return app.exec()


def _ensure_standard_streams() -> None:
    """为无控制台的 PyInstaller 进程提供可写的标准流占位对象。"""

    # `windowed` 启动器会把标准输出和错误流设为 `None`，
    # 但少数第三方库仍会尝试调用它们。指向系统空设备即可避免启动崩溃，
    # 同时不会给用户弹出控制台窗口或泄露日志内容。
    for stream_name in ("stdout", "stderr"):
        if getattr(sys, stream_name) is None:
            setattr(sys, stream_name, open(os.devnull, "w", encoding="utf-8"))


def _run_self_test(report_path: Path, verify_asr_load: bool = False) -> int:
    """写出不依赖控制台的发布包运行报告。"""

    context = bootstrap_application()
    report = build_runtime_report(context.settings)
    items = [
        {"name": item.name, "status": item.status, "message": item.message}
        for item in report.items
    ]

    if verify_asr_load:
        try:
            runtime_message = _load_asr_model_for_self_test(context)
            items.append(
                {
                    "name": "asr_inference",
                    "status": "pass",
                    "message": f"ASR 真实推理成功：{runtime_message}",
                }
            )
        except Exception as exc:
            # 自检必须把失败类型写入报告后退出，不能让窗口模式吞掉异常。
            items.append(
                {
                    "name": "asr_inference",
                    "status": "fail",
                    "message": f"ASR 模型加载失败：{type(exc).__name__}",
                }
            )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            {
                "status": "fail"
                if any(item["status"] == "fail" for item in items)
                else report.status,
                "workspace_root": str(context.workspace.root),
                "database_path": str(context.workspace.database_path),
                "items": items,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return 1 if any(item["status"] == "fail" for item in items) else 0


def _load_asr_model_for_self_test(context) -> str:
    """加载内置 ASR 模型并处理一秒静音，验证动态库和模型文件均可用。"""

    silence_path: Path | None = None
    try:
        temp_dir = context.workspace.root / "temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix="zero-caption-self-test-",
            suffix=".wav",
            dir=temp_dir,
            delete=False,
        ) as handle:
            silence_path = Path(handle.name)
        with wave.open(str(silence_path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16_000)
            audio.writeframes(b"\x00\x00" * 16_000)

        engine = context.container.create_asr_engine()
        if isinstance(engine, AsrRuntimeVerifier):
            return engine.verify_runtime(silence_path, language="en")

        # 兼容未来只实现基础端口的识别适配器。它们仍可完成最小自检，
        # 但若没有运行摘要，就明确返回未知参数而不是猜测设备。
        engine.transcribe(silence_path, language="en")
        if isinstance(engine, AsrRuntimeReporter):
            return engine.runtime_summary()
        return "识别适配器未提供实际运行参数。"
    finally:
        if silence_path is not None:
            silence_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
