<#
  Zero Caption Windows 构建脚本。

  该脚本先使用 PyInstaller 生成自包含便携目录，再使用 Inno Setup 生成单用户安装包。
  FFmpeg、配置、Python 依赖和 ASR 模型都会进入安装目录，目标用户不需要另装软件。
#>

param(
  [string]$PythonPath = '',
  [switch]$SkipDependencyInstall,
  [switch]$SkipModelDownload,
  [switch]$SkipInstallerBuild,
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
}

if (-not $SkipInstallerBuild) {
  # 安装包编译器只属于开发期工具。准备脚本会优先复用本机版本，
  # 缺失时才把官方 Inno Setup 安装到仓库 `.tools` 目录。
  & (Join-Path $PSScriptRoot 'prepare_installer_tool.ps1') | ForEach-Object {
    Write-Host ('installer tool: ' + $_)
  }
  $commandCompiler = Get-Command 'ISCC.exe' -ErrorAction SilentlyContinue
  $compilerCandidates = @(
    (Join-Path $repoRoot '.tools\inno-setup\ISCC.exe'),
    $(if ($commandCompiler) { $commandCompiler.Source } else { $null }),
    (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe')
  )
  $compiler = $compilerCandidates |
    Where-Object { $_ -and (Test-Path -LiteralPath $_) } |
    Select-Object -First 1
  if (-not $compiler -or -not (Test-Path -LiteralPath $compiler)) {
    throw 'Inno Setup compiler was not prepared successfully'
  }

  & $compiler (Join-Path $repoRoot 'installer\ZeroCaption.iss')
  if ($LASTEXITCODE -ne 0) {
    throw ('installer build failed, exit code: ' + $LASTEXITCODE)
  }

  $setup = Get-ChildItem (Join-Path $repoRoot 'dist\installer') -Filter '*-setup.exe' |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
  if (-not $setup) {
    throw 'built installer was not found'
  }
  $checksum = Get-FileHash -LiteralPath $setup.FullName -Algorithm SHA256
  $checksumPath = $setup.FullName + '.sha256'
  Set-Content `
    -LiteralPath $checksumPath `
    -Value ($checksum.Hash + '  ' + $setup.Name) `
    -Encoding ascii
  Write-Host ('installer completed: ' + $setup.FullName)
  Write-Host ('installer checksum: ' + $checksumPath)

  if (-not $SkipVerification) {
    & (Join-Path $PSScriptRoot 'verify_installer.ps1') -SetupPath $setup.FullName
  }
}
