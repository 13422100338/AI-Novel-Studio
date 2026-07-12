@echo off
setlocal
set "ROOT=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%launch.ps1"
if errorlevel 1 (
    echo.
    echo Startup failed. Please copy this window's error message and send it to Codex.
    pause >nul
)
