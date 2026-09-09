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

REM ---- 4. Qt UI (CustomTkinter is gone - the frozen exe is PySide6-only) ----
echo [INFO] Ensuring PySide6 is installed...
python -m pip install "PySide6>=6.6.0"
if errorlevel 1 (
    echo [ERROR] Failed to install PySide6. The Qt UI cannot be bundled without it.
    pause
    exit /b 1
)

REM ---- 4a. WebView2 Python bindings for Brick Breaker in-app play ----
echo [INFO] Ensuring WebView2 Python packages (pythonnet, pywebview)...
python -m pip install "pythonnet>=3.0.0" "pywebview>=5.0"
if errorlevel 1 (
    echo [WARN] Could not install WebView2 Python packages - Brick Breaker in-app play may not work.
)

REM ---- 4a2. YouTube Downloader / yt-dlp runtime ----
REM The source build can see these packages from site-packages, but a
REM PyInstaller one-file build must explicitly collect yt-dlp's dynamic
REM package data and the EJS challenge-solver package.
echo [INFO] Ensuring yt-dlp + EJS + PO-token provider are installed...
python -m pip install --upgrade "yt-dlp[default]" "bgutil-ytdlp-pot-provider"
if errorlevel 1 (
    echo [WARN] Could not update yt-dlp/EJS/PO-token packages.
    echo        Continuing, but the YouTube EXE may fail at runtime.
)

REM ---- 4b. simple-websocket for the Messaging module's WS server ----
echo [INFO] Ensuring simple-websocket is installed (Messaging module)...
python -m pip install "simple-websocket>=1.0.0"
if errorlevel 1 (
    echo [WARN] Could not install simple-websocket - the Messages module's server won't start.
)

REM ---- 4c. Make sure pywin32 is installed AND its postinstall has run ----
REM PyInstaller bundles win32com/pythoncom/pywintypes by walking real DLL
REM dependencies on disk. pip installing pywin32 alone does NOT guarantee
REM pywintypesXX.dll / pythoncomXX.dll exist where that walker looks -
REM pywin32 ships its own postinstall step (normally run automatically by
REM the installer, but skipped by plain `pip install pywin32` in some
REM environments) that copies those two DLLs into
REM Lib\site-packages\pywin32_system32\. Skipping this is what causes a
REM built exe to fail at runtime with "pywin32 isn't installed" even
REM though pywin32 is clearly installed in the build environment.
echo [INFO] Ensuring pywin32 is installed and its postinstall step has run...
python -m pip install --upgrade pywin32 pywin32-ctypes >nul 2>nul
for /f "delims=" %%P in ('python -c "import sysconfig,os;print(os.path.join(sysconfig.get_paths()['purelib'],'pywin32_system32'))"') do set "PYWIN32_SYS32=%%P"
if not exist "%PYWIN32_SYS32%\pythoncom3*.dll" (
    echo [INFO] pywin32 postinstall DLLs missing - running postinstall script...
    for /f "delims=" %%S in ('python -c "import sysconfig,os;print(os.path.join(sysconfig.get_paths()['scripts'],'pywin32_postinstall.py'))"') do set "PYWIN32_POSTINSTALL=%%S"
    if exist "!PYWIN32_POSTINSTALL!" (
        python "!PYWIN32_POSTINSTALL!" -install
        if errorlevel 1 (
            echo [WARN] pywin32 postinstall script failed - the exe may still hit "pywin32 isn't installed" at runtime.
            echo        Try running it manually as Administrator: python "!PYWIN32_POSTINSTALL!" -install
        )
    ) else (
        echo [WARN] Could not locate pywin32_postinstall.py - skipping. If the exe later
        echo        errors with "pywin32 isn't installed", reinstall pywin32 with:
        echo          pip uninstall -y pywin32
        echo          pip install --no-cache-dir pywin32
    )
) else (
    echo [INFO] pywin32 postinstall DLLs already present.
)

REM ---- 5. Refresh the dependency lock file ----
echo [INFO] Writing requirements-lock.txt from currently installed packages...
python -m pip freeze > "requirements-lock.txt"

REM ---- 6. Clean previous build artifacts ----
echo [INFO] Cleaning previous build/dist folders...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
if exist "Zs Multi Tool.spec" del /q "Zs Multi Tool.spec"

REM ---- 7. Run PyInstaller ----
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
REM NOTE: do NOT --collect-all PySide6. That pulls QML/Charts/3D/WebEngine
REM this app never imports, inflates the exe, and emits missing-plugin
REM warnings for files the PySide6 wheel does not even ship. Hidden-import
REM the modules we actually use; PyInstaller's PySide6 hooks grab the
REM platform/style/imageformat plugins. Tk hidden imports stay because
REM the updater dialogs and core.qt.tk_after still import tkinter at launch.
python -m PyInstaller ^
    --noconfirm ^
    --onefile ^
    --windowed ^
    --name "Zs Multi Tool" ^
    --icon "assets\icon.ico" ^
    --additional-hooks-dir hooks ^
    --hidden-import "PySide6.QtCore" ^
    --hidden-import "PySide6.QtGui" ^
    --hidden-import "PySide6.QtWidgets" ^
    --hidden-import "PySide6.QtMultimedia" ^
    --exclude-module customtkinter ^
    --exclude-module PySide6.QtCharts ^
    --exclude-module PySide6.QtQml ^
    --exclude-module PySide6.QtQuick ^
    --exclude-module PySide6.QtQuick3D ^
    --exclude-module PySide6.Qt3DCore ^
    --exclude-module PySide6.QtWebEngine ^
    --exclude-module PySide6.QtWebEngineCore ^
    --exclude-module PySide6.QtWebEngineWidgets ^
    --exclude-module PySide6.QtBluetooth ^
    --exclude-module PySide6.QtPositioning ^
    --exclude-module PySide6.QtSensors ^
    --exclude-module PySide6.QtPdf ^
    --exclude-module PySide6.QtPdfWidgets ^
    --exclude-module PySide6.QtDataVisualization ^
    --exclude-module PySide6.QtGraphs ^
    --collect-all mutagen ^
    --collect-all PIL ^
    --collect-all pystray ^
    --collect-all qrcode ^
    --collect-all openai ^
    --collect-all pywebview ^
    --collect-all clr_loader ^
    --collect-all simple_websocket ^
    --collect-all wsproto ^
    --collect-data pypresence ^
    --hidden-import "PIL._tkinter_finder" ^
    --hidden-import "_tkinter" ^
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
    --collect-all yt_dlp ^
    --collect-all yt_dlp_ejs ^
    --collect-all yt_dlp_plugins ^
    --copy-metadata yt-dlp ^
    --copy-metadata yt-dlp-ejs ^
    --hidden-import "openai" ^
    --hidden-import "simple_websocket" ^
    --hidden-import "wsproto" ^
    --hidden-import "h11" ^
    --hidden-import "webview.platforms.edgechromium" ^
    --hidden-import "webview.platforms.winforms" ^
    --hidden-import "webview.guilib" ^
    --hidden-import "clr" ^
    --hidden-import "pythonnet" ^
    --hidden-import "win32com" ^
    --hidden-import "win32com.client" ^
    --hidden-import "win32timezone" ^
    --hidden-import "win32gui" ^
    --hidden-import "win32con" ^
    --hidden-import "win32api" ^
    --hidden-import "pythoncom" ^
    --hidden-import "pywintypes" ^
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

REM ---- 8. Rename exe to the real name (apostrophe is fine on disk) ----
if exist "dist\Zs Multi Tool.exe" (
    ren "dist\Zs Multi Tool.exe" "Z's Multi Tool.exe"
)

REM ---- 9. Bundle the VLC runtime next to the exe ----
REM python-vlc (used by Media Player) needs libvlc.dll,
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

REM Last resort: auto-download the official VLC win64 portable build via
REM download_vlc.ps1 (see that file for details) so a fresh checkout on a
REM machine with no VLC installed can still produce a self-contained dist\.
if not defined VLC_DIR (
    echo [INFO] No local VLC install found - attempting to auto-download the VLC runtime...
    set "VLC_DOWNLOAD_LINE="
    for /f "usebackq delims=" %%L in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0download_vlc.ps1" -Destination "%~dp0.vlc_cache" 2^>^&1`) do (
        echo %%L
        echo %%L | findstr /b "VLC_DIR=" >nul && set "VLC_DOWNLOAD_LINE=%%L"
    )
    if defined VLC_DOWNLOAD_LINE (
        for /f "tokens=1* delims==" %%A in ("!VLC_DOWNLOAD_LINE!") do set "VLC_DIR=%%B"
        echo [INFO] Auto-downloaded VLC runtime to "!VLC_DIR!"
    ) else (
        echo [WARN] Auto-download of VLC failed - see messages above.
    )
)

if defined VLC_DIR (
    echo [INFO] Found VLC at "%VLC_DIR%" - copying libvlc.dll, libvlccore.dll, plugins\...
    copy /y "%VLC_DIR%\libvlc.dll" "dist\" >nul
    copy /y "%VLC_DIR%\libvlccore.dll" "dist\" >nul
    if exist "dist\plugins" rmdir /s /q "dist\plugins"
    xcopy "%VLC_DIR%\plugins" "dist\plugins\" /e /i /q >nul
    echo [INFO] VLC runtime bundled into dist\.
) else (
    echo [WARN] No VLC runtime found and auto-download failed ^(check your
    echo        internet connection^). Media Player will
    echo        fail with "Could not find module libvlc.dll" until you either:
    echo          - re-run this build with an internet connection so
    echo            download_vlc.ps1 can fetch it automatically, or
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
echo  - yt-dlp, yt-dlp-ejs, and yt-dlp plugin package data are explicitly
echo    collected into the frozen EXE; this is important because the Python
echo    source run can see site-packages directly while the EXE cannot.
echo  - requirements-lock.txt was refreshed with your currently installed
echo    package versions ^(pip freeze^) before this build ran.
echo  - The exe bundles JSON/config files as they exist RIGHT NOW.
echo    If you edit settings.json etc. later, rebuild to include changes.
echo  - python-vlc needs libvlc.dll + the "plugins" folder from your
echo    VLC install sitting next to the exe (or a system-wide VLC install)
echo    for Media Player to work.
echo  - scapy/nmap (network_auditor module) need Npcap and Nmap installed
echo    on any machine that runs the exe, PyInstaller can't bundle those.
echo    If you compile install.iss, the installer will now auto-download
echo    both and launch their installers for you - but note neither one's
echo    free edition supports silent installs, so you'll still click
echo    through those two installer windows once.
echo  - pywin32: this build now checks that pywintypesXX.dll/pythoncomXX.dll
echo    exist (running pywin32's postinstall script if not) before invoking
echo    PyInstaller, since a missing postinstall step is the usual cause of
echo    the exe failing at runtime with "pywin32 isn't installed" even
echo    though pywin32 is pip-installed in the build environment.
echo.
pause