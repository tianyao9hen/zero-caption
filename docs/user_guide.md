# Zero Caption 使用指南

## 首次启动

在 Windows 上启动 `ZeroCaption.exe` 或运行 `python -m app.main`。程序会在配置的工作区中创建项目目录、缓存目录、导出目录、日志目录和 SQLite 数据库。

## 处理视频

1. 点击“导入视频”。
2. 选择本地视频、源语言和目标语言，可选填写作品或术语上下文。
3. 选择“外挂字幕”或“烧录字幕”，确认后等待任务页显示完成。
4. 在项目页查看原视频、项目状态、工作区和最终导出路径。

识别和视频处理在后台线程执行，窗口可以继续切换页面。任务状态会按步骤写入 SQLite，应用异常退出后再次启动会把未完成任务标记为待恢复。

## 翻译配置

在配置文件的 `[engine.translation]` 中填写兼容 OpenAI Chat Completions 的地址和模型名，并在系统环境变量中设置 `api_key_env` 指定的密钥。云端只接收字幕文本、语言和可选上下文，不会接收原始视频或音频。

## 命令行

```powershell
python scripts/process_video.py path/to/video.mp4 --source-language auto --target-language zh-CN
python scripts/process_video.py path/to/video.mp4 --export-mode burn_in
```

## 故障排查

- 使用 `python scripts/check_runtime.py` 检查 FFmpeg、ffprobe、ASR 模型目录和翻译配置。
- 查看应用级 `logs/app.log` 和项目目录下的 `logs/project.jsonl`。
- 需要提交问题时，使用 `DiagnosticBundle` 生成诊断 ZIP；它会排除原始媒体文件。
- 如果任务停留在运行中，重启应用后查看任务页的恢复状态，再根据错误摘要重试。
