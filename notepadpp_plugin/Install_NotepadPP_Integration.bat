@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_notepadpp_integration.ps1"
if errorlevel 1 (
    echo.
    echo Installation failed. Try running this file as Administrator.
    pause
    exit /b 1
)
echo.
pause
endlocal
