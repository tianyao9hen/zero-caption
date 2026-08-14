<#
  Zero Caption 发布前烟雾测试。

  这个脚本不处理真实视频，重点验证依赖导入、运行时工具、数据库初始化、
  Qt 主窗口构造和不依赖真实 ASR 模型的回归测试。
#>

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

python -m compileall -q app core config infrastructure scripts ui
python scripts/check_runtime.py
$env:QT_QPA_PLATFORM = "offscreen"
python -m pytest -q --ignore=tests/integration/test_faster_whisper_engine.py
python -c "from app.bootstrap import bootstrap_application; from PySide6.QtWidgets import QApplication; import sys; app=QApplication.instance() or QApplication(sys.argv); ctx=bootstrap_application(); window=ctx.container.create_main_window(); assert window.windowTitle() == 'Zero Caption'; window.close(); print('desktop startup smoke passed')"

Write-Host "Smoke test completed"
