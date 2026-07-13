@echo off
setlocal
cd /d "%~dp0"

echo [AI Novel Studio] Checking for Python 3.11 or newer...

set "PYTHON_COMMAND=py -3"
%PYTHON_COMMAND% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if not errorlevel 1 goto python_ready

set "PYTHON_COMMAND=python"
%PYTHON_COMMAND% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if not errorlevel 1 goto python_ready

echo.
echo Python 3.11 or newer was not found.
echo Install Python from https://www.python.org/downloads/ and enable "Add Python to PATH".
pause
exit /b 1

:python_ready
if /I "%~1"=="--check" (
    echo Python requirement check passed.
    exit /b 0
)

if exist ".venv\Scripts\python.exe" goto install_dependencies

echo Creating the local virtual environment...
%PYTHON_COMMAND% -m venv .venv
if errorlevel 1 goto failed

:install_dependencies
echo Installing AI Novel Studio and its runtime dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -e .
if errorlevel 1 goto failed

echo.
echo Installation completed successfully.
echo Double-click launch.bat to start AI Novel Studio.
pause
exit /b 0

:failed
echo.
echo Installation failed. Review the error message above and try again.
pause
exit /b 1
