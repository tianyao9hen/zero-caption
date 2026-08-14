# Zero Caption 使用指南

## 首次启动

双击 `ZeroCaption-0.1.0-win64-setup.exe` 完成安装，再从开始菜单打开“Zero Caption”。
安装包默认写入当前用户的 `%LOCALAPPDATA%\Programs\ZeroCaption`，不需要管理员权限。
发布版已经携带 Python、VC 运行库、Qt、FFmpeg、ffprobe、`faster-whisper` 和默认
`small` 本地识别模型，不要求用户另外安装这些软件。程序会在当前用户数据目录的工作区中
创建项目目录、缓存目录、导出目录、日志目录和 SQLite 数据库。

## 处理视频

1. 点击“导入视频”。
2. 未配置大模型时，保留默认的“仅生成原文字幕（本地）”，再选择本地视频和源语言。
3. 已配置大模型时，可以选择“翻译字幕并导出视频”，继续设置目标语言、导出模式和可选上下文。
4. 确认后等待任务页显示完成，再到项目页查看识别音频、字幕文件和可选的视频导出路径。

识别和视频处理在后台线程执行，窗口可以继续切换页面。任务状态会按步骤写入 SQLite，应用异常退出后再次启动会把未完成任务标记为待恢复。

## 翻译配置

打开“设置”页面，在“大模型翻译”分组中填写兼容 OpenAI Chat Completions 的接口地址、模型名称和 API 密钥，并按需要调整超时、重试和批处理边界。保存后，后续任务会立即使用新配置；密钥写入当前用户的 `ZeroCaption/settings.toml`，不会写入日志或翻译正文。API 密钥留空时仍可使用 `OPENAI_API_KEY` 环境变量作为兼容回退。云端只接收字幕文本、语言和可选上下文，不会接收原始视频或音频。

翻译功能依赖用户选择的大模型 API 与网络连接，但不依赖本机安装任何大模型客户端。
未配置翻译接口时，导入表单会默认选择“仅生成原文字幕（本地）”，本地视频导入、
音频抽取和字幕识别仍可独立完成，不会把缺少翻译配置当作任务失败。

## 命令行

```powershell
python scripts/process_video.py path/to/video.mp4 --source-language auto --target-language zh-CN
python scripts/process_video.py path/to/video.mp4 --export-mode burn_in
```

## 故障排查

- 安装包旁的 `.sha256` 文件可用于核对下载文件是否完整。
- 可以在 Windows“已安装的应用”中卸载 Zero Caption；项目与用户配置会保留在 `%LOCALAPPDATA%\ZeroCaption`。
- 使用 `python scripts/check_runtime.py` 检查 FFmpeg、ffprobe、内置 ASR 模型目录和翻译配置。
- 查看应用级 `logs/app.log` 和项目目录下的 `logs/project.jsonl`。
- 需要提交问题时，使用 `DiagnosticBundle` 生成诊断 ZIP；它会排除原始媒体文件。
- 如果任务停留在运行中，重启应用后查看任务页的恢复状态，再根据错误摘要重试。
