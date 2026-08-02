@echo off
setlocal
cd /d "%~dp0"

set "SETTINGS_BACKUP=build\preserved-settings.json"
set "SETTINGS_PRESENT=0"
if exist "dist\EaWFocusTextPreview\settings.json" (
    set "SETTINGS_PRESENT=1"
    if not exist "build" mkdir "build"
    copy /y "dist\EaWFocusTextPreview\settings.json" "%SETTINGS_BACKUP%" >nul
    if errorlevel 1 exit /b 1
)

call notepadpp_plugin\build_plugin.bat
if errorlevel 1 exit /b 1

if not exist ".venv\Scripts\python.exe" (
    py -3.12 -m venv .venv
    if errorlevel 1 py -3 -m venv .venv
    if errorlevel 1 exit /b 1
)

".venv\Scripts\python.exe" -m pip --version >nul 2>&1
if errorlevel 1 ".venv\Scripts\python.exe" -m ensurepip --upgrade
if errorlevel 1 exit /b 1

".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 exit /b 1

".venv\Scripts\python.exe" -m pytest
if errorlevel 1 exit /b 1

".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean EaWFocusTextPreview.spec
if errorlevel 1 exit /b 1

".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --distpath "build\cli-dist" --workpath "build\cli-pyinstaller" EaWFocusTextPreviewCLI.spec
if errorlevel 1 exit /b 1

copy /y "build\cli-dist\EaWFocusTextPreviewCLI\EaWFocusTextPreviewCLI.exe" "dist\EaWFocusTextPreview\EaWFocusTextPreviewCLI.exe" >nul
if errorlevel 1 exit /b 1
xcopy /e /i /y /q "build\cli-dist\EaWFocusTextPreviewCLI\_internal" "dist\EaWFocusTextPreview\_internal" >nul
if errorlevel 1 exit /b 1

if "%SETTINGS_PRESENT%"=="1" (
    copy /y "%SETTINGS_BACKUP%" "dist\EaWFocusTextPreview\settings.json" >nul
    if errorlevel 1 exit /b 1
)

copy /y "README.md" "dist\EaWFocusTextPreview\README.md" >nul
if errorlevel 1 exit /b 1
copy /y "LICENSE" "dist\EaWFocusTextPreview\LICENSE" >nul
if errorlevel 1 exit /b 1
copy /y "THIRD_PARTY_NOTICES.md" "dist\EaWFocusTextPreview\THIRD_PARTY_NOTICES.md" >nul
if errorlevel 1 exit /b 1
copy /y "CHANGELOG.md" "dist\EaWFocusTextPreview\CHANGELOG.md" >nul
if errorlevel 1 exit /b 1
copy /y "settings.example.json" "dist\EaWFocusTextPreview\settings.example.json" >nul
if errorlevel 1 exit /b 1

set "API_INTEGRATION=dist\EaWFocusTextPreview\Integration"
if not exist "%API_INTEGRATION%" mkdir "%API_INTEGRATION%"
copy /y "integration\README_Integration.md" "%API_INTEGRATION%\README_Integration.md" >nul
if errorlevel 1 exit /b 1
copy /y "integration\request.example.json" "%API_INTEGRATION%\request.example.json" >nul
if errorlevel 1 exit /b 1
copy /y "integration\batch.example.json" "%API_INTEGRATION%\batch.example.json" >nul
if errorlevel 1 exit /b 1

set "INTEGRATION=dist\EaWFocusTextPreview\Notepad++ Integration"
if not exist "%INTEGRATION%" mkdir "%INTEGRATION%"
copy /y "notepadpp_plugin\dist\EaWFocusBridge.dll" "%INTEGRATION%\EaWFocusBridge.dll" >nul
if errorlevel 1 exit /b 1
copy /y "notepadpp_plugin\Install_NotepadPP_Integration.bat" "%INTEGRATION%\Install_NotepadPP_Integration.bat" >nul
if errorlevel 1 exit /b 1
copy /y "notepadpp_plugin\install_notepadpp_integration.ps1" "%INTEGRATION%\install_notepadpp_integration.ps1" >nul
if errorlevel 1 exit /b 1
copy /y "notepadpp_plugin\README_NotepadPP.txt" "%INTEGRATION%\README_NotepadPP.txt" >nul
if errorlevel 1 exit /b 1

echo.
echo Done: dist\EaWFocusTextPreview\EaWFocusTextPreview.exe
echo CLI:  dist\EaWFocusTextPreview\EaWFocusTextPreviewCLI.exe
endlocal
