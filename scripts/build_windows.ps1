$ErrorActionPreference = "Stop"
. "$PSScriptRoot\resolve_python.ps1"
$Python = Resolve-ProjectPython
$projectRoot = Split-Path -Parent $PSScriptRoot

Push-Location $projectRoot
try {
    $env:PYTHONPATH = "src"
    $env:QT_QPA_PLATFORM = "offscreen"
    & $Python -m pytest
    & $Python -m ruff check .
    $env:MYPYPATH = "src"
    & $Python -m mypy
    Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
    & $Python -m PyInstaller --noconfirm --clean packaging/AI-Novel-Studio.spec
    if (-not (Test-Path -LiteralPath "dist/AI-Novel-Studio/AI-Novel-Studio.exe")) {
        throw "Packaged executable was not created."
    }
}
finally {
    Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
    Pop-Location
}
