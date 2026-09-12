@echo off
setlocal

cd /d "%~dp0"

:: Check for python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Python is not installed or not in PATH.
    pause
    exit /b 1
)

:: Set up venv if it doesn't exist
if not exist .venv (
    echo Setting up virtual environment...
    python -m venv .venv
)

echo Checking Python dependencies...
.venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.txt

echo.
echo ReClip is starting at http://localhost:8899
echo.

.venv\Scripts\python.exe app.py
pause
