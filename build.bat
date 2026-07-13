@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================
echo   Z's Multi Tool - Build Script
echo ============================================
echo.

REM ---- 1. Check Python is available ----
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found on PATH. Install Python and try again.
    pause
    exit /b 1
)

REM ---- 2. Make sure PyInstaller is installed ----
python -m pip show pyinstaller >nul 2>nul
if errorlevel 1 (
    echo [INFO] PyInstaller not found, installing...
    python -m pip install pyinstaller
    if errorlevel 1 (
        echo [ERROR] Failed to install PyInstaller.
        pause
        exit /b 1
    )
)

REM ---- 3. Close any running instance (it may be sitting in the tray) ----
REM PyInstaller can't overwrite an exe that's still running as a process —
REM easy to hit now that minimizing sends the app to the system tray
REM instead of fully closing it. Kill both possible names: the final
REM renamed exe (what's actually running from a previous build) and the
REM intermediate build name (in case a build got interrupted before rename).
taskkill /f /im "Z's Multi Tool.exe" >nul 2>nul
taskkill /f /im "Zs Multi Tool.exe" >nul 2>nul
timeout /t 1 /nobreak >nul

REM ---- 4. Refresh the dependency lock file ----
echo [INFO] Writing requirements-lock.txt from currently installed packages...
python -m pip freeze > "requirements-lock.txt"

REM ---- 5. Clean previous build artifacts ----
echo [INFO] Cleaning previous build/dist folders...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
if exist "Zs Multi Tool.spec" del /q "Zs Multi Tool.spec"

REM ---- 6. Run PyInstaller ----
echo [INFO] Building exe with PyInstaller...
echo.

REM NOTE: --name deliberately has NO apostrophe. PyInstaller writes the name
REM straight into a single-quoted Python string inside the generated .spec
REM file, so "Z's Multi Tool" breaks that string and crashes the build with
REM a SyntaxError. We build as "Zs Multi Tool" and rename the exe after.
REM NOTE: no --add-data for "data" here on purpose. CryptoService/
REM VaultService/AuthService all resolve through core/paths.py straight to
REM %APPDATA%\ZsMultiTool\... at runtime and only fall back to a local
REM data/ folder for one-time legacy migration if it happens to exist.
REM Bundling it would (a) fail the build on a fresh checkout, since
REM data/ is gitignored and usually won't exist, and (b) if it DID
REM exist, would ship your real vault.json + master.key inside the exe.
python -m PyInstaller ^
    --noconfirm ^
    --onefile ^
    --windowed ^
    --name "Zs Multi Tool" ^
    --icon "assets\icon.ico" ^
    --collect-all customtkinter ^
    --collect-all mutagen ^
    --collect-all PIL ^
    --collect-all pystray ^
    --collect-data pypresence ^
    --hidden-import "PIL._tkinter_finder" ^
    --hidden-import "scapy.all" ^
    --hidden-import "nmap" ^
    --hidden-import "vlc" ^
    --hidden-import "pyperclip" ^
    --hidden-import "pypresence" ^
    --hidden-import "pystray._win32" ^
    --hidden-import "sounddevice" ^
    --hidden-import "soundfile" ^
    --hidden-import "psutil" ^
    --hidden-import "cryptography.fernet" ^
    --hidden-import "yt_dlp" ^
    --hidden-import "pygame" ^
    --hidden-import "pygame.mixer" ^
    --add-data "modules;modules" ^
    --add-data "core;core" ^
    --add-data "pages;pages" ^
    --add-data "assets;assets" ^
    --add-data "settings.json;." ^
    main.py

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed. Scroll up for details.
    pause
    exit /b 1
)

REM ---- 7. Rename exe to the real name (apostrophe is fine on disk) ----
if exist "dist\Zs Multi Tool.exe" (
    ren "dist\Zs Multi Tool.exe" "Z's Multi Tool.exe"
)

echo.
echo ============================================
echo   Build complete!
echo   Your exe is in the "dist" folder.
echo ============================================
echo.
echo NOTE:
echo  - requirements-lock.txt was refreshed with your currently installed
echo    package versions ^(pip freeze^) before this build ran.
echo  - The exe bundles JSON/config files as they exist RIGHT NOW.
echo    If you edit settings.json etc. later, rebuild to include changes.
echo  - python-vlc needs libvlc.dll + the "plugins" folder from your
echo    VLC install sitting next to the exe (or a system-wide VLC install)
echo    for the media_center module's video/audio playback to work.
echo  - scapy/nmap (network_auditor module) need Npcap and Nmap installed
echo    on any machine that runs the exe, PyInstaller can't bundle those.
echo  - Minimizing the window sends it to the system tray (hidden icons
echo    area). The X button still fully quits the app.
echo.
pause