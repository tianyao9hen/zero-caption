# zero-caption

Windows 本地优先的视频字幕生成与翻译桌面应用。

## Status

当前已完成开发计划中阶段 0 至阶段 7 的主要能力：

- PySide6 桌面入口与分层项目结构
- 配置、日志、运行时探针和项目工作区
- FFmpeg / ffprobe 适配器
- faster-whisper 本地语音识别适配器
- 字幕去重、时间轴规整和 SRT 写出
- 无界面的单视频识别主链路与缓存复用
- 云端字幕翻译、外挂字幕和 FFmpeg 烧录导出
- PySide6 后台任务、进度总线和导入参数表单
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

## Runtime Check

在处理真实视频前，可以先运行：

```powershell
python scripts/check_runtime.py
```

这个脚本会检查 `ffmpeg`、`ffprobe`、`faster-whisper` 以及关键翻译配置是否已经准备好。

## Local Transcription

可以通过命令行运行本地识别，不依赖桌面交互页面：

```powershell
python scripts/transcribe_video.py path/to/video.mp4 --source-language auto
```

原文字幕会写入 `data/projects/<project_id>/subtitles/source.srt`。

## Complete MVP Pipeline

配置翻译接口地址、模型和 API 密钥环境变量后，可以运行完整无界面主链路：

```powershell
python scripts/process_video.py path/to/video.mp4 --source-language auto --target-language zh-CN
```

命令会在项目目录中保留原文字幕和译文字幕，并在 `exports/` 下生成视频副本与同名外挂字幕。
需要烧录字幕时追加 `--export-mode burn_in`；桌面导入对话框也可以直接选择导出模式。
