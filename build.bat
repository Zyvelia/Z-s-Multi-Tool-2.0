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

REM ---- 4. WebView2 Python bindings for Brick Breaker in-app play ----
echo [INFO] Ensuring WebView2 Python packages (pythonnet, pywebview)...
python -m pip install "pythonnet>=3.0.0" "pywebview>=5.0"
if errorlevel 1 (
    echo [WARN] Could not install WebView2 Python packages - Brick Breaker in-app play may not work.
)

REM ---- 4b. Make sure pywin32 is installed AND its postinstall has run ----
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
python -m PyInstaller ^
    --noconfirm ^
    --onefile ^
    --windowed ^
    --name "Zs Multi Tool" ^
    --icon "assets\icon.ico" ^
    --additional-hooks-dir hooks ^
    --collect-all customtkinter ^
    --collect-all mutagen ^
    --collect-all PIL ^
    --collect-all pystray ^
    --collect-all qrcode ^
    --collect-all openai ^
    --collect-all pywebview ^
    --collect-all clr_loader ^
    --collect-all playwright ^
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
    --hidden-import "openai" ^
    --hidden-import "webview.platforms.edgechromium" ^
    --hidden-import "webview.platforms.winforms" ^
    --hidden-import "webview.guilib" ^
    --hidden-import "clr" ^
    --hidden-import "pythonnet" ^
    --hidden-import "playwright.sync_api" ^
    --hidden-import "playwright.async_api" ^
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

REM ---- 10. Bundle the Playwright browser binaries next to the exe ----
REM --collect-all playwright above only grabs the playwright PYTHON
REM PACKAGE (its driver/node launcher etc.) - it does NOT grab the actual
REM browser binaries (Chromium/Firefox/WebKit), because those live outside
REM the package in a separate cache folder that `playwright install`
REM downloads to (normally %USERPROFILE%\AppData\Local\ms-playwright).
REM PyInstaller has no way to know that folder exists, so without this
REM step the built exe imports fine but any page.goto()/browser.launch()
REM call fails at runtime with "Executable doesn't exist" because it's
REM looking for browsers that were never bundled.
echo.
echo [INFO] Looking for Playwright browser binaries to bundle...
set "PLAYWRIGHT_CACHE=%LOCALAPPDATA%\ms-playwright"
if exist "%PLAYWRIGHT_CACHE%" (
    echo [INFO] Found Playwright browsers at "%PLAYWRIGHT_CACHE%" - copying into dist\ms-playwright\...
    if exist "dist\ms-playwright" rmdir /s /q "dist\ms-playwright"
    xcopy "%PLAYWRIGHT_CACHE%" "dist\ms-playwright\" /e /i /q >nul
    echo [INFO] Playwright browsers bundled into dist\.
) else (
    echo [WARN] No Playwright browser cache found at "%PLAYWRIGHT_CACHE%".
    echo        Run "python -m playwright install" once on this machine,
    echo        then re-run this build so the browsers get bundled.
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
echo    If you compile install.iss, the installer will now auto-download
echo    both and launch their installers for you - but note neither one's
echo    free edition supports silent installs, so you'll still click
echo    through those two installer windows once.
echo  - Brick Breaker in-app play needs WebView2 Runtime on the PC plus the
echo    pythonnet/pywebview packages bundled by this build script.
echo    The installer can install WebView2 Runtime if it is missing.
echo  - Playwright: the exe now bundles the browser binaries it finds in
echo    %%LOCALAPPDATA%%\ms-playwright (as dist\ms-playwright\). Your app
echo    code needs to point Playwright at that folder at runtime by
echo    setting the PLAYWRIGHT_BROWSERS_PATH environment variable BEFORE
echo    importing playwright, e.g. in main.py:
echo        import os, sys
echo        if getattr(sys, 'frozen', False):
echo            os.environ['PLAYWRIGHT_BROWSERS_PATH'] = os.path.join(
echo                os.path.dirname(sys.executable), 'ms-playwright')
echo    Without that, Playwright will still look in the default per-user
echo    cache path and fail on a machine where it wasn't installed.
echo  - pywin32: this build now checks that pywintypesXX.dll/pythoncomXX.dll
echo    exist (running pywin32's postinstall script if not) before invoking
echo    PyInstaller, since a missing postinstall step is the usual cause of
echo    the exe failing at runtime with "pywin32 isn't installed" even
echo    though pywin32 is pip-installed in the build environment.
echo.
pause