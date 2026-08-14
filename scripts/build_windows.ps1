<#
  Zero Caption Windows 构建脚本。

  该脚本使用 PyInstaller 生成便携式目录，FFmpeg、配置和资源文件通过
  `--add-data` 一并复制。首次构建前请在当前 Python 环境安装 PyInstaller。
#>

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

python -m PyInstaller --noconfirm --clean `
  --name ZeroCaption `
  --windowed `
  --paths $repoRoot `
  --add-data "config;config" `
  --add-data "resources;resources" `
  --collect-all PySide6 `
  app/main.py

Write-Host "构建完成：$repoRoot\dist\ZeroCaption"
