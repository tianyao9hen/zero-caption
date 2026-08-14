# zero-caption

Windows 本地优先的视频字幕生成与翻译桌面应用。

## Status

当前已完成开发计划中的阶段 0、阶段 1 和阶段 2 本地识别链路：

- PySide6 桌面入口与分层项目结构
- 配置、日志、运行时探针和项目工作区
- FFmpeg / ffprobe 适配器
- faster-whisper 本地语音识别适配器
- 字幕去重、时间轴规整和 SRT 写出
- 无界面的单视频识别主链路与缓存复用

翻译、视频导出、桌面流程接入和 SQLite 恢复能力仍在后续阶段开发。

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

在进入后续识别、翻译和导出开发前，可以先运行：

```powershell
python scripts/check_runtime.py
```

这个脚本会检查 `ffmpeg`、`ffprobe`、`faster-whisper` 以及关键翻译配置是否已经准备好。

## Local Transcription

阶段 2 可以先通过命令行运行本地识别，不依赖尚未完成的桌面交互页面：

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
