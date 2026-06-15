# zero-caption

Video subtitle generation and translation desktop app skeleton for Windows.

## Status

This repository currently contains the application shell only:

- PySide6 desktop entrypoint
- layered project structure
- configuration loading
- logging bootstrap
- workspace directory management
- placeholder UI pages and dialogs

No real subtitle, translation, export, or database features are implemented yet.

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
