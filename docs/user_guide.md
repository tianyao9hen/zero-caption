# Zero Caption 使用指南

## 首次启动

双击 `ZeroCaption-0.1.0-win64-setup.exe` 完成安装，再从开始菜单打开“Zero Caption”。
安装包默认写入当前用户的 `%LOCALAPPDATA%\Programs\ZeroCaption`，不需要管理员权限。
发布版已经携带 Python、VC 运行库、Qt、FFmpeg、ffprobe、`faster-whisper`、`cuBLAS 12`，以及
`small`、`medium` 两套本地识别模型，不要求用户另外安装或在首次任务时下载这些内容。
程序会在当前用户数据目录的工作区中创建项目目录、缓存目录、导出目录、日志目录和
SQLite 数据库。

## 本地识别与 GPU 设置

打开“设置”页面，在“本地字幕识别”分组中选择模型、运行设备和推理精度：

- “自动”会根据实际硬件选择安全组合。
- 5GB 以上可用 NVIDIA GPU 默认推荐 `medium + CUDA + float16`，字幕质量高于 `small`。
- 没有可用 CUDA 时默认使用 `small + CPU + int8`。
- 显存较小可以选择 `small` 或 `int8_float16`，降低显存压力。
- “GPU 失败时自动切换到 CPU”默认开启，驱动或 CUDA 运行库异常时任务仍可继续。
- 安装版已携带 GPU 推理所需的 `cuBLAS 12`，用户不需要安装完整 CUDA Toolkit；
  NVIDIA 显卡驱动仍需由系统正常提供。

页面会显示检测到的显卡名称、显存、CUDA 状态和推荐组合。点击“应用硬件推荐”只会
填充表单，需要再点击“保存引擎设置”才会影响后续任务。同一个模型切换到 GPU 主要提高
速度；质量提升主要来自 GPU 允许使用更强的 `medium` 模型。

## 处理视频

1. 点击“导入视频”。
2. 未配置大模型时，保留默认的“仅生成原文字幕（本地）”，再选择本地视频和源语言。
3. 已配置大模型时，可以选择“翻译字幕并导出视频”，继续设置目标语言、导出模式和可选上下文。
4. 确认后可在任务页实时查看每条字幕的原文和译文，再到项目页查看识别音频、字幕文件和可选的视频导出路径。

识别和视频处理在后台线程执行，窗口可以继续切换页面。任务状态会按步骤写入 SQLite，应用异常退出后再次启动会把未完成任务标记为待恢复。

## 翻译配置

打开“设置”页面，在“大模型翻译”分组中填写兼容 OpenAI Chat Completions 的接口地址、模型名称和 API 密钥，并按需要调整系统提示词、超时和重试参数。点击“保存引擎设置”后，后续翻译会立即使用新提示词；密钥写入当前用户的 `ZeroCaption/settings.toml`，不会写入日志或翻译正文。API 密钥留空时仍可使用 `OPENAI_API_KEY` 环境变量作为兼容回退。云端只接收字幕文本、语言和可选上下文，不会接收原始视频或音频。

“大模型测试”区域可以输入一次性用户提示词，并使用当前表单中的接口、模型、密钥和系统提示词在后台请求；无需先保存，测试期间窗口不会阻塞。正式字幕翻译固定每条字幕分别调用一次模型，每条完成后立即保存检查点并显示在任务页，后续条目失败时不会丢失已经完成的译文。

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
- 使用 `python scripts/check_runtime.py` 检查 FFmpeg、ffprobe、两套内置 ASR 模型、GPU 建议和翻译配置。
- CUDA 不可用时查看设置页硬件建议；应用会继续使用 CPU，不会阻止本地字幕生成。
- 查看应用级 `logs/app.log` 和项目目录下的 `logs/project.jsonl`。
- 需要提交问题时，使用 `DiagnosticBundle` 生成诊断 ZIP；它会排除原始媒体文件。
- 如果任务停留在运行中，重启应用后查看任务页的恢复状态，再根据错误摘要重试。
