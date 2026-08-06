[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$buildRoot = Join-Path $projectRoot '.build'
$venv = Join-Path $buildRoot 'venv'
$python = $null

if ($env:PYTHON -and (Test-Path -LiteralPath $env:PYTHON)) {
    $python = $env:PYTHON
} else {
    $candidate = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($candidate) { $python = $candidate.Source }
}
if (-not $python) {
    throw '没有找到 Python 3.11 或更高版本。可通过环境变量 PYTHON 指定 python.exe。'
}

New-Item -ItemType Directory -Force -Path $buildRoot | Out-Null
if (-not (Test-Path -LiteralPath (Join-Path $venv 'Scripts\python.exe'))) {
    & $python -m venv $venv
}
$venvPython = Join-Path $venv 'Scripts\python.exe'
& $venvPython -m pip install --disable-pip-version-check --upgrade 'pyinstaller==6.16.0'

Push-Location $projectRoot
try {
    & $venvPython -m PyInstaller --noconfirm --clean --onefile --windowed `
        --name AirMirrorLAN --icon assets\AirMirrorLAN.ico `
        --paths src src\airmirror_app.py
    Copy-Item -LiteralPath dist\AirMirrorLAN.exe -Destination .\AirMirrorLAN.exe -Force
} finally {
    Pop-Location
}
Write-Host "构建完成：$projectRoot\AirMirrorLAN.exe" -ForegroundColor Green
