$ErrorActionPreference = "Stop"
$env:PYTHONPATH = "src"
$env:QT_QPA_PLATFORM = "offscreen"
python -m pytest
python -m ruff check .
$env:MYPYPATH = "src"
python -m mypy
Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
python -m PyInstaller --noconfirm --clean packaging/AI-Novel-Studio.spec
if (-not (Test-Path -LiteralPath "dist/AI-Novel-Studio/AI-Novel-Studio.exe")) {
    throw "Packaged executable was not created."
}
