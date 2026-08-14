<#
  Zero Caption 发布目录验收脚本。

  该脚本从临时工作目录启动已经构建好的 GUI 程序，检查自检报告、用户数据目录
  和真实主窗口。自检阶段使用隐藏进程，主窗口阶段保持可见，以覆盖用户实际启动路径。
#>

param(
  [string]$ExecutablePath = "",
  [int]$StartupTimeoutSeconds = 30
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not $ExecutablePath) {
  $ExecutablePath = Join-Path $repoRoot "dist\ZeroCaption\ZeroCaption.exe"
}
$executable = (Resolve-Path -LiteralPath $ExecutablePath).Path

$runRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("zero-caption-package-" + [guid]::NewGuid().ToString("N"))
$workingDirectory = Join-Path $runRoot "unrelated-working-directory"
$localAppData = Join-Path $runRoot "local-app-data"
$reportPath = Join-Path $runRoot "self-test.json"
New-Item -ItemType Directory -Force -Path $workingDirectory, $localAppData | Out-Null

$oldLocalAppData = $env:LOCALAPPDATA
$selfTest = $null
$guiProcess = $null

try {
  $env:LOCALAPPDATA = $localAppData

  # 第一步：自检进程不显示控制台，报告通过 JSON 文件返回。
  $selfTest = Start-Process -FilePath $executable -ArgumentList ('--self-test-report "' + $reportPath + '" --verify-asr-load') -WorkingDirectory $workingDirectory -WindowStyle Hidden -PassThru
  $selfTestDeadline = (Get-Date).AddSeconds(180)
  while (-not (Test-Path -LiteralPath $reportPath) -and (Get-Date) -lt $selfTestDeadline) {
    Start-Sleep -Milliseconds 250
  }
  if (-not (Test-Path -LiteralPath $reportPath)) {
    throw 'packaged self-test did not produce a report within 180 seconds'
  }

  $report = Get-Content -Raw -Encoding utf8 -LiteralPath $reportPath | ConvertFrom-Json
  $requiredPasses = @("ffmpeg", "ffprobe", "faster_whisper", "asr_model", "asr_inference", "model_cache_dir")
  foreach ($name in $requiredPasses) {
    $item = @($report.items | Where-Object { $_.name -eq $name }) | Select-Object -First 1
    if (-not $item -or $item.status -ne "pass") {
      throw ("packaged self-test item failed: " + $name)
    }
  }

  # 自检报告写入后，进程仍需要一点时间释放 `small` 模型占用的内存和文件句柄。
  # 等待它完整退出后再启动 GUI，可以避免两份模型短时间并存导致笔记本内存压力过大。
  if (-not $selfTest.WaitForExit(30000)) {
    throw 'packaged self-test did not exit within 30 seconds after writing its report'
  }
  if ($selfTest.ExitCode -ne 0) {
    throw ("packaged self-test exited with code " + $selfTest.ExitCode)
  }

  # 第二步：从无关工作目录启动真实 GUI，并等待 Qt 创建主窗口句柄。
  $guiProcess = Start-Process -FilePath $executable -WorkingDirectory $workingDirectory -PassThru
  $deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
  do {
    Start-Sleep -Milliseconds 250
    $guiProcess.Refresh()
    if ($guiProcess.HasExited) {
      throw ("packaged GUI exited before creating a window, exit code: " + $guiProcess.ExitCode)
    }
  } while ($guiProcess.MainWindowHandle -eq 0 -and (Get-Date) -lt $deadline)
  if ($guiProcess.MainWindowHandle -eq 0) {
    throw ("packaged GUI did not create a window within " + $StartupTimeoutSeconds + " seconds")
  }

  $workspaceRoot = Join-Path $localAppData "ZeroCaption\data"
  $requiredPaths = @(
    (Join-Path $workspaceRoot "projects"),
    (Join-Path $workspaceRoot "cache"),
    (Join-Path $workspaceRoot "exports"),
    (Join-Path $workspaceRoot "logs"),
    (Join-Path $workspaceRoot "zero_caption.sqlite3")
  )
  foreach ($path in $requiredPaths) {
    if (-not (Test-Path -LiteralPath $path)) {
      throw ("packaged app did not create expected user path: " + $path)
    }
  }

  Write-Host "发布包验收通过：$executable"
  Write-Host "自检报告：$reportPath"
}
finally {
  if ($guiProcess -and -not $guiProcess.HasExited) {
    Stop-Process -Id $guiProcess.Id -Force
  }
  if ($selfTest -and -not $selfTest.HasExited) {
    Stop-Process -Id $selfTest.Id -Force
  }
  $env:LOCALAPPDATA = $oldLocalAppData
}
