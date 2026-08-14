<#
  Zero Caption smoke test for Windows releases.

  The script checks imports, runtime tools, database initialization, Qt startup,
  and the non-ASR regression suite without processing a real video.
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
