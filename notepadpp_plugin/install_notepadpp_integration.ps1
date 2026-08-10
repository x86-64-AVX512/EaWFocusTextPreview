param(
    [string]$NotepadPath = "",
    [switch]$Elevated
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pluginCandidates = @(
    (Join-Path $scriptRoot "EaWFocusBridge.dll"),
    (Join-Path $scriptRoot "dist\EaWFocusBridge.dll")
)
$pluginDll = $pluginCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1

$appCandidates = @(
    (Join-Path (Split-Path -Parent $scriptRoot) "EaWFocusTextPreview.exe"),
    (Join-Path (Split-Path -Parent $scriptRoot) "dist\EaWFocusTextPreview\EaWFocusTextPreview.exe")
)
$appExe = $appCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $appExe) {
    throw "EaWFocusTextPreview.exe was not found next to the integration package."
}
if (-not $pluginDll) {
    throw "EaWFocusBridge.dll was not found."
}

if (-not $NotepadPath) {
    $running = Get-Process "notepad++" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($running -and $running.Path) {
        $NotepadPath = $running.Path
    }
}
if (-not $NotepadPath) {
    $candidates = @(
        "$env:ProgramFiles\Notepad++\notepad++.exe",
        "${env:ProgramFiles(x86)}\Notepad++\notepad++.exe",
        "$env:LOCALAPPDATA\Programs\Notepad++\notepad++.exe"
    )
    $NotepadPath = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $NotepadPath -or -not (Test-Path -LiteralPath $NotepadPath)) {
    throw "Notepad++ was not found. Pass its full path with -NotepadPath."
}
if (Get-Process "notepad++" -ErrorAction SilentlyContinue) {
    throw "Close Notepad++ before installing or updating EaW Focus Bridge."
}

$notepadDirectory = Split-Path -Parent (Resolve-Path -LiteralPath $NotepadPath)
$pluginDirectory = Join-Path $notepadDirectory "plugins\EaWFocusBridge"

$programFilesRoots = @(
    [Environment]::GetFolderPath([Environment+SpecialFolder]::ProgramFiles),
    [Environment]::GetFolderPath([Environment+SpecialFolder]::ProgramFilesX86)
) | Where-Object { $_ }
$requiresElevation = $false
foreach ($root in $programFilesRoots) {
    if ($notepadDirectory.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) {
        $requiresElevation = $true
        break
    }
}
$isAdministrator = (
    New-Object Security.Principal.WindowsPrincipal(
        [Security.Principal.WindowsIdentity]::GetCurrent()
    )
).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($requiresElevation -and -not $isAdministrator -and -not $Elevated) {
    $arguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", ('"{0}"' -f $MyInvocation.MyCommand.Path),
        "-NotepadPath", ('"{0}"' -f $NotepadPath),
        "-Elevated"
    )
    $process = Start-Process powershell.exe -Verb RunAs -Wait -PassThru -ArgumentList $arguments
    exit $process.ExitCode
}

New-Item -ItemType Directory -Path $pluginDirectory -Force | Out-Null
Copy-Item -LiteralPath $pluginDll -Destination (Join-Path $pluginDirectory "EaWFocusBridge.dll") -Force

$resolvedExe = (Resolve-Path -LiteralPath $appExe).Path
$ini = "[Bridge]`r`nExePath=$resolvedExe`r`n"
[System.IO.File]::WriteAllText(
    (Join-Path $pluginDirectory "EaWFocusBridge.ini"),
    $ini,
    (New-Object System.Text.UTF8Encoding($false))
)

Write-Host "EaW Focus Bridge 0.7.7F1 installed:"
Write-Host $pluginDirectory
Write-Host "Start Notepad++ and use Alt + double left click inside quoted text."
