$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = if ($env:PYTHON) { $env:PYTHON } else { 'python.exe' }
& $python (Join-Path $projectRoot 'src\airmirror_app.py')
