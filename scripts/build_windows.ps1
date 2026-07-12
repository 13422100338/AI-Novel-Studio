$ErrorActionPreference = "Stop"
. "$PSScriptRoot\resolve_python.ps1"
$Python = Resolve-ProjectPython
$projectRoot = Split-Path -Parent $PSScriptRoot
$previousTemp = $env:TEMP
$previousTmp = $env:TMP
$testTemp = Join-Path $projectRoot ".test-temp\build-windows"
$testTempParent = Split-Path -Parent $testTemp
New-Item -ItemType Directory -Path $testTempParent -Force | Out-Null

Push-Location $projectRoot
try {
    $env:PYTHONPATH = "src"
    $env:QT_QPA_PLATFORM = "offscreen"
    $env:TEMP = $testTemp
    $env:TMP = $testTemp
    & $Python -m pytest -p no:cacheprovider --basetemp $testTemp
    if ($LASTEXITCODE -ne 0) { throw "pytest failed with exit code $LASTEXITCODE." }
    & $Python -m ruff check .
    if ($LASTEXITCODE -ne 0) { throw "Ruff failed with exit code $LASTEXITCODE." }
    $env:MYPYPATH = "src"
    & $Python -m mypy
    if ($LASTEXITCODE -ne 0) { throw "mypy failed with exit code $LASTEXITCODE." }
    Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
    & $Python -m PyInstaller --noconfirm --clean packaging/AI-Novel-Studio.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE." }
    if (-not (Test-Path -LiteralPath "dist/AI-Novel-Studio/AI-Novel-Studio.exe")) {
        throw "Packaged executable was not created."
    }
}
finally {
    $env:TEMP = $previousTemp
    $env:TMP = $previousTmp
    Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
    Pop-Location
}
