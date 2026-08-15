# zero-caption

Windows 本地优先的视频字幕生成与翻译桌面应用。

## Status

当前已完成开发计划中阶段 0 至阶段 7 的主要能力：

- PySide6 桌面入口与分层项目结构
- 配置、日志、运行时探针和项目工作区
- FFmpeg / ffprobe 适配器
- faster-whisper 本地语音识别适配器
- NVIDIA GPU 自动探测、CPU 回退和 `small` / `medium` 模型切换
- 字幕去重、时间轴规整和 SRT 写出
- 无界面的单视频识别主链路与缓存复用
- 云端字幕翻译、外挂字幕和 FFmpeg 烧录导出
- PySide6 后台任务、进度总线和集中式任务创建表单
- 按视频聚合的持久化任务工作区、阶段详情和逐句译文
- SQLite 项目/任务/字幕/导出记录与可恢复任务队列
- ASS 字幕、项目日志、诊断包和 Windows 打包烟测脚本

首次启动会在工作区内创建 `zero_caption.sqlite3`，用于保存项目历史和任务状态。

## Run

```powershell
pip install -e .
python -m app.main
```

## Test

```powershell
python -m pytest
```

## Windows 发布包

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_windows.ps1
```

构建脚本会同时生成：

- `dist/ZeroCaption/`：免安装便携目录。
- `dist/installer/ZeroCaption-0.1.0-win64-setup.exe`：推荐给最终用户的单用户安装包。

两个版本均已包含 Python、VC 运行库、Qt、FFmpeg、ffprobe、`faster-whisper`、
`cuBLAS 12` 运行依赖，以及 `small`、`medium` 两套本地模型。自动模式会在可用的 5GB 以上
NVIDIA CUDA GPU 上选择 `medium + float16`，无可用 GPU 时选择 `small + CPU + int8`。
用户也可以在设置页自行选择模型、设备和精度；CUDA 初始化失败时默认自动回退 CPU。
目标电脑无需安装 Python、FFmpeg、完整 CUDA Toolkit 或临时下载识别模型，只需保持
NVIDIA 显卡驱动可用。字幕翻译仍需要用户配置可访问的
大模型 API，但不会要求安装任何翻译客户端。

## Runtime Check

在处理真实视频前，可以先运行：

```powershell
python scripts/check_runtime.py
```

这个脚本会检查 `ffmpeg`、`ffprobe`、`faster-whisper`、两套内置模型、
CUDA 硬件建议以及关键翻译配置是否已经准备好。

## Local Transcription

可以通过命令行运行本地识别，不依赖桌面交互页面：

```powershell
python scripts/transcribe_video.py path/to/video.mp4 --source-language auto
```

原文字幕会写入 `data/projects/<project_id>/subtitles/source.srt`。桌面“创建视频任务”表单提供
“自动识别语言并生成原文字幕（本地）”处理方式，未配置大模型时会默认选中该方式，并跳过翻译和视频导出。

## Complete MVP Pipeline

可在桌面应用的“设置”页配置翻译接口地址、模型、API 密钥和系统提示词；也可以使用
`OPENAI_API_KEY` 环境变量作为密钥回退。设置页支持输入用户提示词后台测试当前表单配置。
正式翻译会逐条独立调用模型，并在任务页实时追加原文和译文。配置完成后，可以运行完整无界面主链路：

```powershell
python scripts/process_video.py path/to/video.mp4 --source-language auto --target-language zh-CN
```

命令会在项目目录中保留原文字幕和译文字幕，并在 `exports/` 下生成视频副本与同名外挂字幕。
需要烧录字幕时追加 `--export-mode burn_in`；桌面导入对话框也可以直接选择导出模式。
