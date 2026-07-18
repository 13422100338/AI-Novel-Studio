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
if /I "%~1"=="--verify" goto verify_environment

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

:verify_environment
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo The local virtual environment was not found. Run setup.bat first.
    goto failed
)

echo Checking installed dependency compatibility...
".venv\Scripts\python.exe" -m pip check
if errorlevel 1 goto failed

echo Checking required Python modules...
".venv\Scripts\python.exe" -c "import PySide6; import ai_novel_studio; from ai_novel_studio.app import create_application"
if errorlevel 1 goto failed

echo Running the headless application startup test...
set "AI_NOVEL_STUDIO_LAUNCH_SMOKE=1"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch.ps1"
set "SMOKE_EXIT=%ERRORLEVEL%"
set "AI_NOVEL_STUDIO_LAUNCH_SMOKE="
if not "%SMOKE_EXIT%"=="0" goto failed

echo.
if /I "%~1"=="--verify" (
    echo Installation verification completed successfully.
) else (
    echo Installation completed and verified successfully.
    echo Double-click launch.bat to start AI Novel Studio.
)
pause
exit /b 0

:failed
echo.
echo Installation failed. Review the error message above and try again.
pause
exit /b 1
