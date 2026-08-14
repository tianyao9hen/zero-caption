<#
  Zero Caption Windows 构建脚本。

  该脚本使用 PyInstaller 生成便携式目录，FFmpeg、配置、Python 依赖和 ASR
  模型通过 `ZeroCaption.spec` 一并复制。默认使用仓库 `.venv`，并在缺少模型时下载。
#>

param(
  [string]$PythonPath = '',
  [switch]$SkipDependencyInstall,
  [switch]$SkipModelDownload,
  [switch]$SkipVerification
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if (-not $PythonPath) {
  $venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
  $PythonPath = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { 'python' }
}

function Invoke-Python {
  param(
    [Parameter(Position = 0, ValueFromRemainingArguments = $true)]
    [string[]]$Arguments
  )
  & $PythonPath @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw ('Python command failed, exit code: ' + $LASTEXITCODE)
  }
}

if (-not $SkipDependencyInstall) {
  $dependencyArguments = @('-m', 'pip', 'install', '-e', '.[build]')
  Invoke-Python -Arguments $dependencyArguments
}

if (-not $SkipModelDownload) {
  $modelArguments = @('scripts/prepare_asr_model.py')
  Invoke-Python -Arguments $modelArguments
}

$defaultModel = (& $PythonPath -c "from config.settings import load_settings; print(load_settings('config/default.toml').engine.asr.model_name)").Trim()
if (-not $defaultModel) {
  throw 'default ASR model name is empty'
}
$modelDirectory = Join-Path $repoRoot (Join-Path 'resources\models' $defaultModel)
foreach ($requiredModelFile in @('config.json', 'model.bin', 'tokenizer.json')) {
  if (-not (Test-Path -LiteralPath (Join-Path $modelDirectory $requiredModelFile))) {
    throw ('missing bundled ASR model file: ' + $requiredModelFile)
  }
}
$buildArguments = @('-m', 'PyInstaller', '--noconfirm', '--clean', 'ZeroCaption.spec')
Invoke-Python -Arguments $buildArguments

$executable = Join-Path $repoRoot 'dist\ZeroCaption\ZeroCaption.exe'
if (-not (Test-Path -LiteralPath $executable)) {
  throw ('built executable not found: ' + $executable)
}
Write-Host ('build completed: ' + $executable)

if (-not $SkipVerification) {
  & (Join-Path $PSScriptRoot 'verify_packaged_app.ps1') -ExecutablePath $executable
  if ($LASTEXITCODE -ne 0) {
    throw 'package verification failed'
  }
}
