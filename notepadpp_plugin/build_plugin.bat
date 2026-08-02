@echo off
setlocal
cd /d "%~dp0"

set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if not exist "%VSWHERE%" (
    echo Visual Studio Installer was not found.
    exit /b 1
)

set "VSINSTALL="
for /f "usebackq tokens=*" %%I in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VSINSTALL=%%I"
if not defined VSINSTALL (
    echo Visual Studio with Desktop development with C++ was not found.
    exit /b 1
)

call "%VSINSTALL%\Common7\Tools\VsDevCmd.bat" -no_logo -arch=x64 -host_arch=x64
if errorlevel 1 exit /b 1

if not exist "build" mkdir "build"
if not exist "dist" mkdir "dist"

cl /nologo /std:c++17 /O2 /W4 /WX /EHsc /utf-8 /Fo:build\quote_extract_tests.obj /Fd:build\quote_extract_tests.pdb tests\quote_extract_tests.cpp /Fe:build\quote_extract_tests.exe
if errorlevel 1 exit /b 1
build\quote_extract_tests.exe
if errorlevel 1 exit /b 1

cl /nologo /std:c++17 /O2 /W4 /WX /EHsc /utf-8 /Fo:build\alt_double_click_smoke.obj /Fd:build\alt_double_click_smoke.pdb tests\alt_double_click_smoke.cpp user32.lib /Fe:build\alt_double_click_smoke.exe
if errorlevel 1 exit /b 1

rc /nologo /fo build\version.res src\version.rc
if errorlevel 1 exit /b 1

cl /nologo /std:c++17 /O2 /W4 /WX /EHsc /utf-8 /DUNICODE /D_UNICODE /DNOMINMAX /LD /Fo:build\plugin.obj /Fd:build\EaWFocusBridge.pdb src\plugin.cpp build\version.res /link /NOLOGO /OUT:dist\EaWFocusBridge.dll /IMPLIB:build\EaWFocusBridge.lib shell32.lib user32.lib
if errorlevel 1 exit /b 1

echo Done: dist\EaWFocusBridge.dll
endlocal
