@echo off
setlocal
cd /d "%~dp0"

echo [INFO] Building CLIENT from the shared root main.py...
echo [INFO] Client build does NOT bundle developer publisher code.
echo [INFO] Client build does NOT bundle source modules; modules are installed from the marketplace.
echo.

if not exist "main.py" (
    echo [ERROR] main.py was not found in the project root.
    pause
    exit /b 1
)

if not exist "core" (
    echo [ERROR] core\ was not found in the project root.
    pause
    exit /b 1
)

if not exist "pages" (
    echo [ERROR] pages\ was not found in the project root.
    pause
    exit /b 1
)

if exist "ClientBuild" rmdir /s /q "ClientBuild"
if exist "ZsMultiToolClient.spec" del /q "ZsMultiToolClient.spec"

pyinstaller --noconfirm --clean --name "ZsMultiTool" --windowed --onedir ^
    --paths "." ^
    --collect-submodules core ^
    --collect-submodules pages ^
    main.py

if errorlevel 1 (
    echo.
    echo [ERROR] Client build failed.
    pause
    exit /b 1
)

if exist "dist\ZsMultiTool" move /y "dist\ZsMultiTool" "ClientBuild" >nul

echo.
echo [OK] Client build complete:
echo     ClientBuild\
echo.
echo [INFO] Source modules were intentionally NOT bundled.
echo       Install modules through Marketplace after launching the client.
echo.
pause
