# Zero Caption 使用指南

## 首次启动

在 Windows 上启动 `ZeroCaption.exe` 或运行 `python -m app.main`。发布版已经携带 Python、FFmpeg、ffprobe 和默认 `small` 本地识别模型，不要求用户另外安装这些软件。程序会在当前用户数据目录的工作区中创建项目目录、缓存目录、导出目录、日志目录和 SQLite 数据库。

## 处理视频

1. 点击“导入视频”。
2. 选择本地视频、源语言和目标语言，可选填写作品或术语上下文。
3. 选择“外挂字幕”或“烧录字幕”，确认后等待任务页显示完成。
4. 在项目页查看原视频、项目状态、工作区和最终导出路径。

识别和视频处理在后台线程执行，窗口可以继续切换页面。任务状态会按步骤写入 SQLite，应用异常退出后再次启动会把未完成任务标记为待恢复。

## 翻译配置

打开“设置”页面，在“大模型翻译”分组中填写兼容 OpenAI Chat Completions 的接口地址、模型名称和 API 密钥，并按需要调整超时、重试和批处理边界。保存后，后续任务会立即使用新配置；密钥写入当前用户的 `ZeroCaption/settings.toml`，不会写入日志或翻译正文。API 密钥留空时仍可使用 `OPENAI_API_KEY` 环境变量作为兼容回退。云端只接收字幕文本、语言和可选上下文，不会接收原始视频或音频。

## 命令行

```powershell
python scripts/process_video.py path/to/video.mp4 --source-language auto --target-language zh-CN
python scripts/process_video.py path/to/video.mp4 --export-mode burn_in
```

## 故障排查

- 使用 `python scripts/check_runtime.py` 检查 FFmpeg、ffprobe、内置 ASR 模型目录和翻译配置。
- 查看应用级 `logs/app.log` 和项目目录下的 `logs/project.jsonl`。
- 需要提交问题时，使用 `DiagnosticBundle` 生成诊断 ZIP；它会排除原始媒体文件。
- 如果任务停留在运行中，重启应用后查看任务页的恢复状态，再根据错误摘要重试。
