@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================
echo   Z's Multi Tool - Build Script (CONSOLE / DEBUG BUILD)
echo ============================================
echo.
echo This build keeps a visible console window attached, so any
echo print() output and unhandled tracebacks (plugin load failures,
echo errors when opening a tool, etc.) show up live instead of being
echo silently swallowed like they are in the normal --windowed build.
echo It is meant for debugging only - use build.bat for the real release.
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
REM PyInstaller can't overwrite an exe that's still running as a process -
REM easy to hit now that minimizing sends the app to the system tray
REM instead of fully closing it. Kill both possible names: the final
REM renamed exe (what's actually running from a previous build) and the
REM intermediate build name (in case a build got interrupted before rename).
taskkill /f /im "Z's Multi Tool (Console).exe" >nul 2>nul
taskkill /f /im "Zs Multi Tool (Console).exe" >nul 2>nul
timeout /t 1 /nobreak >nul

REM ---- 4. Refresh the dependency lock file ----
echo [INFO] Writing requirements-lock.txt from currently installed packages...
python -m pip freeze > "requirements-lock.txt"

REM ---- 5. Clean previous build artifacts ----
echo [INFO] Cleaning previous build/dist folders...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
if exist "Zs Multi Tool (Console).spec" del /q "Zs Multi Tool (Console).spec"

REM ---- 6. Run PyInstaller ----
echo [INFO] Building exe with PyInstaller...
echo.

REM NOTE: --name deliberately has NO apostrophe. PyInstaller writes the name
REM straight into a single-quoted Python string inside the generated .spec
REM file, so "Z's Multi Tool" breaks that string and crashes the build with
REM a SyntaxError. We build as "Zs Multi Tool (Console)" and rename the exe
REM after.
REM NOTE: --console instead of --windowed is the only functional difference
REM from build.bat - everything else (collected packages, hidden imports,
REM bundled data) is identical so this build behaves the same, it just
REM shows its console.
REM NOTE: --collect-all openai / --hidden-import openai / the three winrt
REM hidden-imports + --collect-all winrt were added to match
REM Zs_Multi_Tool.spec (this script had fallen out of sync with it - it
REM predates the AI Chat module). Without --collect-all openai, the AI
REM Chat module's "from openai import OpenAI" fails at runtime with
REM ModuleNotFoundError, plugin_manager.py's try/except swallows it, and
REM the module just silently never appears - this is exactly the bug this
REM console build exists to catch.
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
    --console ^
    --uac-admin ^
    --name "Zs Multi Tool (Console)" ^
    --icon "assets\icon.ico" ^
    --collect-all customtkinter ^
    --collect-all mutagen ^
    --collect-all PIL ^
    --collect-all pystray ^
    --collect-all qrcode ^
    --collect-all openai ^
    --collect-all winrt ^
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
    --hidden-import "openai" ^
    --hidden-import "winrt.windows.foundation" ^
    --hidden-import "winrt.windows.ui.notifications" ^
    --hidden-import "winrt.windows.ui.notifications.management" ^
    --hidden-import "win32com" ^
    --hidden-import "win32com.client" ^
    --hidden-import "win32timezone" ^
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

REM ---- 7. Rename exe to the real name (apostrophe is fine on disk) ----
if exist "dist\Zs Multi Tool (Console).exe" (
    ren "dist\Zs Multi Tool (Console).exe" "Z's Multi Tool (Console).exe"
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
    echo        internet connection^). media_center and music_player will
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
echo   Console debug build complete!
echo   Your exe is in the "dist" folder.
echo ============================================
echo.
echo NOTE:
echo  - This exe opens WITH a console window attached. Run it from
echo    Explorer or a terminal and watch that console for
echo    [PluginManager]/[PageManager]/[App] print() lines and any
echo    unhandled tracebacks - this is the fastest way to see exactly
echo    why a module failed to load or errored on open.
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
echo    If you compile install.iss, the installer will now auto-download
echo    both and launch their installers for you - but note neither one's
echo    free edition supports silent installs, so you'll still click
echo    through those two installer windows once.
echo  - Minimizing the window sends it to the system tray (hidden icons
echo    area). The X button still fully quits the app.
echo  - This console build and the normal build.bat build can coexist:
echo    they use different --name values ("Zs Multi Tool (Console)" vs
echo    "Zs Multi Tool"), so building one never overwrites the other's
echo    exe in dist\ as long as you don't run both builds back to back
echo    without moving the first exe out of dist\ first.
echo.
pause