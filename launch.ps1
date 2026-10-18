$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
. "$PSScriptRoot\scripts\resolve_python.ps1"
$python = Resolve-ProjectPython
$pythonw = Join-Path (Split-Path -Parent $python) "pythonw.exe"
$env:PYTHONPATH = Join-Path $projectRoot "src"
if ($env:AI_NOVEL_STUDIO_LAUNCH_SMOKE -eq "1") {
    $env:QT_QPA_PLATFORM = "offscreen"
    @'
from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication
from ai_novel_studio.ui_qml.bootstrap import create_engine
app = QGuiApplication(["launcher-smoke"])
engine = create_engine()
if not engine.rootObjects():
    raise SystemExit("QML startup failed")
QTimer.singleShot(0, app.quit)
raise SystemExit(app.exec())
'@ | & $python -
    exit $LASTEXITCODE
}
if (-not (Test-Path -LiteralPath $pythonw)) {
    $pythonw = $python
}
$process = Start-Process `
    -FilePath $pythonw `
    -ArgumentList @("-m", "ai_novel_studio.ui_qml") `
    -WorkingDirectory $projectRoot `
    -WindowStyle Normal `
    -PassThru
Start-Sleep -Seconds 1
if ($process.HasExited -and $process.ExitCode -ne 0) {
    throw "AI Novel Studio exited during startup with code $($process.ExitCode)."
}
