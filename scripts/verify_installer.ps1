<#
  Zero Caption 安装包验收脚本。

  脚本会把安装包静默安装到带空格的自定义临时目录，并调用发布目录验收脚本
  检查模型、媒体工具、用户数据目录和真实 GUI。随后执行两轮卸载：第一轮
  验证默认保留历史记录，第二轮通过 `/CLEANHISTORY` 验证彻底清理用户数据。
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

function Invoke-ZeroCaptionInstall {
  param(
    [Parameter(Mandatory = $true)]
    [string]$InstallerPath,
    [Parameter(Mandatory = $true)]
    [string]$InstallDirectory,
    [Parameter(Mandatory = $true)]
    [string]$LogPath
  )

  # `/DIR` 覆盖默认路径，带空格的目录同时保护安装器的命令行转义行为。
  $installArguments = @(
    '/VERYSILENT',
    '/SUPPRESSMSGBOXES',
    '/NORESTART',
    '/NOICONS',
    ('/DIR="' + $InstallDirectory + '"'),
    ('/LOG="' + $LogPath + '"')
  )
  $installProcess = Start-Process `
    -FilePath $InstallerPath `
    -ArgumentList $installArguments `
    -WindowStyle Hidden `
    -Wait `
    -PassThru
  if ($installProcess.ExitCode -ne 0) {
    throw ('安装包静默安装失败，退出码：' + $installProcess.ExitCode)
  }
}

function Assert-RejectsUnsafeInstallDirectory {
  param(
    [Parameter(Mandatory = $true)]
    [string]$InstallerPath,
    [Parameter(Mandatory = $true)]
    [string]$UnsafeDirectory,
    [Parameter(Mandatory = $true)]
    [string]$LogPath
  )

  # 非空目录里先放一份“个人文件”，安装器必须拒绝并保持文件原样。
  $personalFile = Join-Path $UnsafeDirectory 'personal-file.txt'
  New-Item -ItemType Directory -Force -Path $UnsafeDirectory | Out-Null
  Set-Content -LiteralPath $personalFile -Value '安装器不得覆盖或删除' -Encoding utf8

  $installArguments = @(
    '/VERYSILENT',
    '/SUPPRESSMSGBOXES',
    '/NORESTART',
    '/NOICONS',
    ('/DIR="' + $UnsafeDirectory + '"'),
    ('/LOG="' + $LogPath + '"')
  )
  $installProcess = Start-Process `
    -FilePath $InstallerPath `
    -ArgumentList $installArguments `
    -WindowStyle Hidden `
    -Wait `
    -PassThru

  if ($installProcess.ExitCode -eq 0) {
    throw '安装器错误地接受了包含个人文件的非空目录。'
  }
  if (-not (Test-Path -LiteralPath $personalFile)) {
    throw '安装器拒绝非空目录时修改了其中的个人文件。'
  }
  if (Test-Path -LiteralPath (Join-Path $UnsafeDirectory 'ZeroCaption.exe')) {
    throw '安装器拒绝非空目录后仍复制了程序文件。'
  }
}

function Assert-InstalledPayload {
  param(
    [Parameter(Mandatory = $true)]
    [string]$InstallDirectory
  )

  # 这些文件覆盖桌面运行时、媒体工具、CPU/GPU 推理依赖和两套 ASR 模型。
  foreach ($requiredPath in @(
    (Join-Path $InstallDirectory 'ZeroCaption.exe'),
    (Join-Path $InstallDirectory 'unins000.exe'),
    (Join-Path $InstallDirectory '.zero-caption-install-root'),
    (Join-Path $InstallDirectory '_internal\python313.dll'),
    (Join-Path $InstallDirectory '_internal\vcruntime140.dll'),
    (Join-Path $InstallDirectory '_internal\msvcp140.dll'),
    (Join-Path $InstallDirectory '_internal\PySide6\Qt6Core.dll'),
    (Join-Path $InstallDirectory '_internal\PySide6\plugins\platforms\qwindows.dll'),
    (Join-Path $InstallDirectory '_internal\ctranslate2\ctranslate2.dll'),
    (Join-Path $InstallDirectory '_internal\nvidia\cublas\bin\cublas64_12.dll'),
    (Join-Path $InstallDirectory '_internal\nvidia\cublas\bin\cublasLt64_12.dll'),
    (Join-Path $InstallDirectory '_internal\onnxruntime\capi\onnxruntime.dll'),
    (Join-Path $InstallDirectory '_internal\resources\bin\ffmpeg\ffmpeg.exe'),
    (Join-Path $InstallDirectory '_internal\resources\bin\ffmpeg\ffprobe.exe'),
    (Join-Path $InstallDirectory '_internal\resources\models\small\model.bin'),
    (Join-Path $InstallDirectory '_internal\resources\models\medium\model.bin')
  )) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
      throw ('安装后缺少必需的内置运行文件：' + $requiredPath)
    }
  }
}

function Wait-RemovedPath {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path,
    [Parameter(Mandatory = $true)]
    [string]$Description
  )

  # Inno Setup 的卸载程序会从临时副本完成自删除，目录消失可能稍晚于进程退出。
  $cleanupDeadline = (Get-Date).AddSeconds(15)
  while ((Test-Path -LiteralPath $Path) -and (Get-Date) -lt $cleanupDeadline) {
    Start-Sleep -Milliseconds 250
  }
  if (Test-Path -LiteralPath $Path) {
    throw ($Description + '：' + $Path)
  }
}

function Invoke-ZeroCaptionUninstall {
  param(
    [Parameter(Mandatory = $true)]
    [string]$UninstallerPath,
    [Parameter(Mandatory = $true)]
    [string]$InstallDirectory,
    [Parameter(Mandatory = $true)]
    [string]$LogPath,
    [switch]$CleanHistory,
    [string]$TestHistoryDirectory = ''
  )

  $uninstallArguments = @(
    '/VERYSILENT',
    '/SUPPRESSMSGBOXES',
    '/NORESTART',
    ('/LOG="' + $LogPath + '"')
  )
  if ($CleanHistory) {
    $uninstallArguments += '/CLEANHISTORY'
    if ($TestHistoryDirectory) {
      # 安装器只接受位于 `zero-caption-installer-*` 临时根目录下的隔离路径。
      # 正式用户卸载不会传入这个内部验收参数，仍使用系统用户数据目录。
      $uninstallArguments += ('/TESTHISTORYROOT="' + $TestHistoryDirectory + '"')
    }
  }

  $uninstallProcess = Start-Process `
    -FilePath $UninstallerPath `
    -ArgumentList $uninstallArguments `
    -WindowStyle Hidden `
    -Wait `
    -PassThru
  if ($uninstallProcess.ExitCode -ne 0) {
    throw ('安装包自带卸载程序执行失败，退出码：' + $uninstallProcess.ExitCode)
  }

  Wait-RemovedPath `
    -Path $InstallDirectory `
    -Description '卸载完成后仍残留安装目录'
}

$runRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('zero-caption-installer-' + [guid]::NewGuid().ToString('N'))
$installRoot = Join-Path $runRoot 'custom install location\Zero Caption'
$unsafeInstallRoot = Join-Path $runRoot 'directory with personal files'
$localAppDataRoot = Join-Path $runRoot 'local-app-data'
$historyRoot = Join-Path $localAppDataRoot 'ZeroCaption'
$firstSetupLog = Join-Path $runRoot 'setup-preserve-history.log'
$unsafeSetupLog = Join-Path $runRoot 'setup-reject-unsafe-directory.log'
$firstUninstallLog = Join-Path $runRoot 'uninstall-preserve-history.log'
$secondSetupLog = Join-Path $runRoot 'setup-clean-history.log'
$secondUninstallLog = Join-Path $runRoot 'uninstall-clean-history.log'
New-Item -ItemType Directory -Force -Path $runRoot | Out-Null

$oldLocalAppData = $env:LOCALAPPDATA
try {
  $env:LOCALAPPDATA = $localAppDataRoot

  # 安全边界：带有个人文件且没有应用所有权标记的目录必须在复制前被拒绝。
  Assert-RejectsUnsafeInstallDirectory `
    -InstallerPath $setup `
    -UnsafeDirectory $unsafeInstallRoot `
    -LogPath $unsafeSetupLog

  # 第一轮：验证自定义目录安装和真实发布程序，再确认普通静默卸载会保留历史记录。
  Invoke-ZeroCaptionInstall `
    -InstallerPath $setup `
    -InstallDirectory $installRoot `
    -LogPath $firstSetupLog
  Assert-InstalledPayload -InstallDirectory $installRoot

  $executable = Join-Path $installRoot 'ZeroCaption.exe'
  & (Join-Path $PSScriptRoot 'verify_packaged_app.ps1') -ExecutablePath $executable

  $preservedHistoryMarker = Join-Path $historyRoot 'data\history-preserved.marker'
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $preservedHistoryMarker) | Out-Null
  Set-Content -LiteralPath $preservedHistoryMarker -Value '卸载后应保留' -Encoding utf8
  Set-Content `
    -LiteralPath (Join-Path $installRoot 'runtime-generated-residue.tmp') `
    -Value '卸载时应随安装目录删除' `
    -Encoding utf8

  Invoke-ZeroCaptionUninstall `
    -UninstallerPath (Join-Path $installRoot 'unins000.exe') `
    -InstallDirectory $installRoot `
    -LogPath $firstUninstallLog
  if (-not (Test-Path -LiteralPath $preservedHistoryMarker)) {
    throw '未选择清理历史记录时，卸载程序错误地删除了用户数据。'
  }

  # 第二轮：重新安装到同一自定义目录，并显式要求清理所有应用历史记录。
  Invoke-ZeroCaptionInstall `
    -InstallerPath $setup `
    -InstallDirectory $installRoot `
    -LogPath $secondSetupLog
  Assert-InstalledPayload -InstallDirectory $installRoot
  Set-Content `
    -LiteralPath (Join-Path $installRoot 'second-runtime-residue.tmp') `
    -Value '第二轮卸载时也应删除' `
    -Encoding utf8

  Invoke-ZeroCaptionUninstall `
    -UninstallerPath (Join-Path $installRoot 'unins000.exe') `
    -InstallDirectory $installRoot `
    -LogPath $secondUninstallLog `
    -CleanHistory `
    -TestHistoryDirectory $historyRoot
  Wait-RemovedPath `
    -Path $historyRoot `
    -Description '选择清理后仍残留历史记录目录'
}
finally {
  # 验收中途失败时尽力调用卸载程序，避免把数 GB 发布文件留在临时目录。
  $remainingUninstaller = Join-Path $installRoot 'unins000.exe'
  if (Test-Path -LiteralPath $remainingUninstaller) {
    try {
      Invoke-ZeroCaptionUninstall `
        -UninstallerPath $remainingUninstaller `
        -InstallDirectory $installRoot `
        -LogPath (Join-Path $runRoot 'uninstall-emergency-cleanup.log') `
        -CleanHistory `
        -TestHistoryDirectory $historyRoot
    }
    catch {
      Write-Warning ('验收失败后的安装目录清理也失败：' + $_.Exception.Message)
    }
  }
  $env:LOCALAPPDATA = $oldLocalAppData
}

Write-Host ('安装包验收通过：' + $setup)
Write-Host '自定义目录安装、应用启动、完整卸载、历史保留与历史清理均已完成。'
