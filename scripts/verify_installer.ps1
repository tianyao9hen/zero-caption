<#
  Zero Caption 安装包验收脚本。

  脚本把安装包静默安装到临时目录，再调用发布目录验收脚本验证模型、媒体工具、
  用户数据目录和真实 GUI。结束时使用安装包自带卸载程序清理测试安装。
#>

param(
  [string]$SetupPath = ''
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not $SetupPath) {
  $SetupPath = Get-ChildItem (Join-Path $repoRoot 'dist\installer') -Filter '*-setup.exe' |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1 -ExpandProperty FullName
}
if (-not $SetupPath) {
  throw '未找到待验收的 Zero Caption 安装包。'
}
$setup = (Resolve-Path -LiteralPath $SetupPath).Path

$runRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('zero-caption-installer-' + [guid]::NewGuid().ToString('N'))
$installRoot = Join-Path $runRoot 'installed-app'
$setupLog = Join-Path $runRoot 'setup.log'
$uninstallLog = Join-Path $runRoot 'uninstall.log'
New-Item -ItemType Directory -Force -Path $runRoot | Out-Null

$oldLocalAppData = $env:LOCALAPPDATA
$uninstaller = $null
try {
  # 第一步：覆盖默认安装目录并禁用快捷方式，避免自动验收修改用户桌面或开始菜单。
  $env:LOCALAPPDATA = Join-Path $runRoot 'local-app-data'
  $installArguments = @(
    '/VERYSILENT',
    '/SUPPRESSMSGBOXES',
    '/NORESTART',
    '/NOICONS',
    ('/DIR="' + $installRoot + '"'),
    ('/LOG="' + $setupLog + '"')
  )
  $installProcess = Start-Process `
    -FilePath $setup `
    -ArgumentList $installArguments `
    -WindowStyle Hidden `
    -Wait `
    -PassThru
  if ($installProcess.ExitCode -ne 0) {
    throw ('安装包静默安装失败，退出码：' + $installProcess.ExitCode)
  }

  $executable = Join-Path $installRoot 'ZeroCaption.exe'
  $uninstaller = Join-Path $installRoot 'unins000.exe'
  foreach ($requiredPath in @(
    $executable,
    $uninstaller,
    (Join-Path $installRoot '_internal\python313.dll'),
    (Join-Path $installRoot '_internal\vcruntime140.dll'),
    (Join-Path $installRoot '_internal\msvcp140.dll'),
    (Join-Path $installRoot '_internal\PySide6\Qt6Core.dll'),
    (Join-Path $installRoot '_internal\PySide6\plugins\platforms\qwindows.dll'),
    (Join-Path $installRoot '_internal\ctranslate2\ctranslate2.dll'),
    (Join-Path $installRoot '_internal\onnxruntime\capi\onnxruntime.dll'),
    (Join-Path $installRoot '_internal\resources\bin\ffmpeg\ffmpeg.exe'),
    (Join-Path $installRoot '_internal\resources\bin\ffmpeg\ffprobe.exe'),
    (Join-Path $installRoot '_internal\resources\models\small\model.bin')
  )) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
      throw ('安装后缺少必需的内置运行文件：' + $requiredPath)
    }
  }

  # 第二步：在隔离环境变量下执行与便携版相同的真实启动和模型加载验收。
  & (Join-Path $PSScriptRoot 'verify_packaged_app.ps1') -ExecutablePath $executable
}
finally {
  # 内层 `finally` 保证即使卸载程序本身失败，也会先恢复调用者的环境变量。
  try {
    if ($uninstaller -and (Test-Path -LiteralPath $uninstaller)) {
      $uninstallArguments = @(
        '/VERYSILENT',
        '/SUPPRESSMSGBOXES',
        '/NORESTART',
        ('/LOG="' + $uninstallLog + '"')
      )
      $uninstallProcess = Start-Process `
        -FilePath $uninstaller `
        -ArgumentList $uninstallArguments `
        -WindowStyle Hidden `
        -Wait `
        -PassThru
      if ($uninstallProcess.ExitCode -ne 0) {
        throw ('安装包自带卸载程序执行失败，退出码：' + $uninstallProcess.ExitCode)
      }

      # 卸载程序可能需要短暂等待自身退出后再删除最后一个目录。
      $cleanupDeadline = (Get-Date).AddSeconds(15)
      while ((Test-Path -LiteralPath $installRoot) -and (Get-Date) -lt $cleanupDeadline) {
        Start-Sleep -Milliseconds 250
      }
      if (Test-Path -LiteralPath $installRoot) {
        throw ('卸载完成后仍残留安装目录：' + $installRoot)
      }
    }
  }
  finally {
    $env:LOCALAPPDATA = $oldLocalAppData
  }
}

Write-Host ('安装包验收通过：' + $setup)
Write-Host '安装、隔离环境启动和卸载清理均已完成。'
