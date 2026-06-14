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
