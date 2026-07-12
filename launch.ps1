$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$pythonw = Join-Path $projectRoot ".venv\Scripts\pythonw.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Python virtual environment was not found: $python"
}
$env:PYTHONPATH = Join-Path $projectRoot "src"
if ($env:AI_NOVEL_STUDIO_LAUNCH_SMOKE -eq "1") {
    $env:QT_QPA_PLATFORM = "offscreen"
    @'
from PySide6.QtCore import QTimer
from ai_novel_studio.app import create_application, main
app = create_application(["launcher-smoke"])
QTimer.singleShot(0, app.quit)
raise SystemExit(main(["launcher-smoke"]))
'@ | & $python -
    exit $LASTEXITCODE
}
if (-not (Test-Path -LiteralPath $pythonw)) {
    $pythonw = $python
}
$process = Start-Process `
    -FilePath $pythonw `
    -ArgumentList @("-m", "ai_novel_studio") `
    -WorkingDirectory $projectRoot `
    -PassThru
Start-Sleep -Seconds 1
if ($process.HasExited -and $process.ExitCode -ne 0) {
    throw "AI Novel Studio exited during startup with code $($process.ExitCode)."
}
