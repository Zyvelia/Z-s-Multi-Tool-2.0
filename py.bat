@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo   Z's Multi Tool - Launcher
echo ============================================
echo.

REM ---- 1. Make sure Python is on PATH ----
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python was not found on PATH.
    echo Install Python 3.11+ from https://python.org and make sure
    echo "Add python.exe to PATH" is checked during setup, then re-run this.
    pause
    exit /b 1
)

python --version

REM ---- 2. Install/verify dependencies every run (cheap no-op if already met) ----
echo.
echo [INFO] Checking dependencies...
python -m pip install -r requirements.txt --disable-pip-version-check -q
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to install one or more dependencies from requirements.txt.
    echo Scroll up to see which package failed - that is almost always why
    echo the app then fails to start.
    pause
    exit /b 1
)

REM ---- 3. Run the app ----
echo.
echo [INFO] Starting Z's Multi Tool...
echo.
python main.py
if errorlevel 1 (
    echo.
    echo [ERROR] The app crashed on startup or during use - see the traceback above.
    echo If you are reporting this, copy everything above this line.
)

pause
