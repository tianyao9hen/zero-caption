<#
  准备 Windows 安装包编译工具。

  `Inno Setup` 只在开发机打包时使用，目标用户不需要安装它。
  脚本优先复用已有编译器；找不到时使用 `winget` 下载经过哈希校验的官方安装程序，
  并把编译器安装到仓库的 `.tools` 忽略目录，避免污染项目提交。
#>

param(
  [string]$Version = '6.7.3'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$toolRoot = Join-Path $repoRoot '.tools\inno-setup'
$localCompiler = Join-Path $toolRoot 'ISCC.exe'

if (Test-Path -LiteralPath $localCompiler) {
  Write-Output $localCompiler
  return
}

$installedCompiler = Get-Command 'ISCC.exe' -ErrorAction SilentlyContinue
if ($installedCompiler) {
  Write-Output $installedCompiler.Source
  return
}

$commonCandidates = @(
  (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
  (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe')
)
foreach ($candidate in $commonCandidates) {
  if ($candidate -and (Test-Path -LiteralPath $candidate)) {
    Write-Output $candidate
    return
  }
}

$winget = Get-Command 'winget.exe' -ErrorAction SilentlyContinue
if (-not $winget) {
  throw '未找到 Inno Setup 编译器，且当前构建机没有 winget，无法自动准备安装包工具。'
}

$downloadRoot = Join-Path $repoRoot '.tools\downloads\inno-setup'
New-Item -ItemType Directory -Force -Path $downloadRoot, $toolRoot | Out-Null

# 第一步：由 `winget` 获取官方安装程序并校验清单中的 SHA256。
& $winget.Source download `
  --id 'JRSoftware.InnoSetup' `
  --exact `
  --version $Version `
  --accept-source-agreements `
  --download-directory $downloadRoot
if ($LASTEXITCODE -ne 0) {
  throw ('winget 下载 Inno Setup 失败，退出码：' + $LASTEXITCODE)
}

$installer = Get-ChildItem -LiteralPath $downloadRoot -Filter '*.exe' |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1
if (-not $installer) {
  throw ('下载完成但未找到 Inno Setup 安装程序：' + $downloadRoot)
}

# 第二步：静默安装到仓库工具目录。这里不申请管理员权限，也不写入应用发布目录。
$arguments = @(
  '/VERYSILENT',
  '/SUPPRESSMSGBOXES',
  '/NORESTART',
  '/SP-',
  '/CURRENTUSER',
  ('/DIR="' + $toolRoot + '"')
)
$process = Start-Process `
  -FilePath $installer.FullName `
  -ArgumentList $arguments `
  -WindowStyle Hidden `
  -Wait `
  -PassThru
if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $localCompiler)) {
  throw ('Inno Setup 准备失败，退出码：' + $process.ExitCode)
}

Write-Output $localCompiler
