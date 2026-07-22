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
    --add-data "modules;modules" ^
    --add-data "core;core" ^
    --add-data "pages;pages" ^
    --add-data "assets;assets" ^
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

REM ---- 8. Bundle the VLC runtime next to the exe ----
REM python-vlc (used by media_center AND music_player) needs libvlc.dll,
REM libvlccore.dll, and the whole plugins\ folder sitting next to the exe -
REM PyInstaller can't discover/bundle these on its own since they're not
REM Python packages. Auto-detect a local VLC install and copy them in so
REM `dist\` ends up self-contained.
echo.
echo [INFO] Looking for a VLC runtime to bundle...
set "VLC_DIR="
REM Installed VLC takes priority - it's more likely to be a current,
REM patched build than whatever's been sitting in the project root.
if exist "%ProgramFiles%\VideoLAN\VLC\libvlc.dll" set "VLC_DIR=%ProgramFiles%\VideoLAN\VLC"
if not defined VLC_DIR if exist "%ProgramFiles(x86)%\VideoLAN\VLC\libvlc.dll" set "VLC_DIR=%ProgramFiles(x86)%\VideoLAN\VLC"
REM Falls back to a vendored copy in the project root (next to build.bat)
REM if no install was found - lets the build still work on a machine with
REM no VLC installed system-wide at all.
if not defined VLC_DIR if exist "%~dp0libvlc.dll" if exist "%~dp0plugins" set "VLC_DIR=%~dp0."

if defined VLC_DIR (
    echo [INFO] Found VLC at "%VLC_DIR%" - copying libvlc.dll, libvlccore.dll, plugins\...
    copy /y "%VLC_DIR%\libvlc.dll" "dist\" >nul
    copy /y "%VLC_DIR%\libvlccore.dll" "dist\" >nul
    if exist "dist\plugins" rmdir /s /q "dist\plugins"
    xcopy "%VLC_DIR%\plugins" "dist\plugins\" /e /i /q >nul
    echo [INFO] VLC runtime bundled into dist\.
) else (
    echo [WARN] No VLC runtime found. media_center and music_player will
    echo        fail with "Could not find module libvlc.dll" until you either:
    echo          - drop libvlc.dll, libvlccore.dll, and a plugins\ folder
    echo            straight into this project's root folder ^(next to
    echo            build.bat^) and re-run this build, or
    echo          - install VLC from videolan.org on this machine and
    echo            re-run this build, or
    echo          - manually copy those same files into dist\ yourself.
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
echo    for the media_center AND music_player modules to work (music_player
echo    switched from pygame to VLC so it isn't blocked by pygame lagging
echo    behind on new Python releases).
echo  - scapy/nmap (network_auditor module) need Npcap and Nmap installed
echo    on any machine that runs the exe, PyInstaller can't bundle those.
echo  - Minimizing the window sends it to the system tray (hidden icons
echo    area). The X button still fully quits the app.
echo.
pause