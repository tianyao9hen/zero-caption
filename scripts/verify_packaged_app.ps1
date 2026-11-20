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
$selfTestReport = Join-Path $runRoot "startup-report.json"
New-Item -ItemType Directory -Force -Path $workingDirectory, $localAppData | Out-Null

$environmentNames = @(
  'LOCALAPPDATA',
  'PATH',
  'PYTHONHOME',
  'PYTHONPATH',
  'VIRTUAL_ENV',
  'CONDA_PREFIX',
  'HF_HOME',
  'HUGGINGFACE_HUB_CACHE',
  'HF_HUB_OFFLINE',
  'TRANSFORMERS_OFFLINE'
)
$oldEnvironment = @{}
foreach ($name in $environmentNames) {
  $oldEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
$guiProcess = $null

try {
  # 验收进程只保留 Windows 系统目录，并清除所有本机 Python、虚拟环境和模型缓存提示。
  # 这样即使开发机已经安装了完整工具链，发布程序也不能无意中借用它们通过测试。
  $env:LOCALAPPDATA = $localAppData
  $env:PATH = (Join-Path $env:SystemRoot 'System32') + ';' + $env:SystemRoot
  foreach ($name in @(
    'PYTHONHOME',
    'PYTHONPATH',
    'VIRTUAL_ENV',
    'CONDA_PREFIX',
    'HF_HOME',
    'HUGGINGFACE_HUB_CACHE'
  )) {
    [Environment]::SetEnvironmentVariable($name, $null, 'Process')
  }
  $env:HF_HUB_OFFLINE = '1'
  $env:TRANSFORMERS_OFFLINE = '1'

  # 先运行与 GUI 共用的启动装配流程，确认路径、日志和数据库都能在隔离环境中初始化。
  # 自检报告独立于 Qt，因此也能把“装配失败”和“Qt 窗口启动失败”区分开。
  $selfTestProcess = Start-Process `
    -FilePath $executable `
    -ArgumentList @('--self-test-report', $selfTestReport, '--verify-qt-import') `
    -WorkingDirectory $workingDirectory `
    -PassThru `
    -Wait
  if ($selfTestProcess.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $selfTestReport)) {
    throw ("packaged startup self-test failed, exit code: " + $selfTestProcess.ExitCode)
  }
  # 应用以 UTF-8 写出中文自检消息，而 Windows PowerShell 5.1 的默认读取编码
  # 是系统 ANSI 代码页；显式指定 UTF-8 可避免把中文字节解码成非法 JSON 字符。
  $selfTestJson = [System.IO.File]::ReadAllText(
    $selfTestReport,
    [System.Text.Encoding]::UTF8
  )
  $selfTest = ConvertFrom-Json -InputObject $selfTestJson
  $qtImport = @($selfTest.items | Where-Object { $_.name -eq 'qt_widgets_import' })
  if ($qtImport.Count -ne 1 -or $qtImport[0].status -ne 'pass') {
    throw "packaged QtWidgets import check failed: $($qtImport[0].message)"
  }
  $requiredPaths = @(
    (Join-Path $selfTest.workspace_root "projects"),
    (Join-Path $selfTest.workspace_root "cache"),
    (Join-Path $selfTest.workspace_root "exports"),
    (Join-Path $selfTest.workspace_root "logs"),
    $selfTest.database_path
  )
  $missingPaths = @($requiredPaths | Where-Object { -not (Test-Path -LiteralPath $_) })
  if ($missingPaths.Count -gt 0) {
    throw ("packaged app did not create expected user paths: " + ($missingPaths -join ", "))
  }

  # 再从相同隔离环境启动真实 GUI；Qt DLL 导入失败时进程会提前退出或无法创建窗口。
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

  Write-Host "发布包验收通过：$executable"
  Write-Host "隔离环境启动装配、用户数据目录和 GUI 窗口检查通过。"
}
finally {
  if ($guiProcess -and -not $guiProcess.HasExited) {
    Stop-Process -Id $guiProcess.Id -Force
  }
  foreach ($name in $environmentNames) {
    [Environment]::SetEnvironmentVariable($name, $oldEnvironment[$name], 'Process')
  }
}
