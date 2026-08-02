[CmdletBinding()]
param(
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$sourcePackage = Join-Path $projectRoot "dist\EaWFocusTextPreview"
$releaseRoot = Join-Path $projectRoot "release"

$versionSource = Get-Content -LiteralPath (
    Join-Path $projectRoot "eaw_focus_preview\__init__.py"
) -Raw -Encoding UTF8
$versionMatch = [regex]::Match(
    $versionSource,
    '__version__\s*=\s*"([^"]+)"'
)
if (-not $versionMatch.Success) {
    throw "Cannot read version from eaw_focus_preview\__init__.py"
}
$version = $versionMatch.Groups[1].Value

Push-Location $projectRoot
try {
    if (-not $SkipBuild) {
        & cmd.exe /d /c build_exe.bat
        if ($LASTEXITCODE -ne 0) {
            throw "build_exe.bat failed with exit code $LASTEXITCODE"
        }
    }

    $requiredFiles = @(
        "EaWFocusTextPreview.exe",
        "EaWFocusTextPreviewCLI.exe",
        "_internal",
        "Integration",
        "Notepad++ Integration",
        "README.md"
    )
    foreach ($relativePath in $requiredFiles) {
        $requiredPath = Join-Path $sourcePackage $relativePath
        if (-not (Test-Path -LiteralPath $requiredPath)) {
            throw "Required build output is missing: $requiredPath"
        }
    }

    New-Item -ItemType Directory -Path $releaseRoot -Force | Out-Null
    $stagingRoot = Join-Path $releaseRoot ".staging-$version"
    $releaseRootResolved = [System.IO.Path]::GetFullPath($releaseRoot)
    $stagingResolved = [System.IO.Path]::GetFullPath($stagingRoot)
    if (-not $stagingResolved.StartsWith(
        $releaseRootResolved + [System.IO.Path]::DirectorySeparatorChar,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Unsafe staging directory: $stagingResolved"
    }

    if (Test-Path -LiteralPath $stagingResolved) {
        Remove-Item -LiteralPath $stagingResolved -Recurse -Force
    }
    New-Item -ItemType Directory -Path $stagingResolved | Out-Null

    try {
        Copy-Item -Path (Join-Path $sourcePackage "*") `
            -Destination $stagingResolved -Recurse -Force

        # The user settings file contains an absolute local path and must
        # never be included in a public archive.
        Remove-Item -LiteralPath (Join-Path $stagingResolved "settings.json") `
            -Force -ErrorAction SilentlyContinue

        foreach ($publicDocument in @(
            "README.md",
            "CHANGELOG.md",
            "LICENSE",
            "THIRD_PARTY_NOTICES.md",
            "settings.example.json"
        )) {
            Copy-Item -LiteralPath (
                Join-Path $projectRoot $publicDocument
            ) -Destination $stagingResolved -Force
        }

        $licenseDestination = Join-Path $stagingResolved "Licenses"
        New-Item -ItemType Directory -Path $licenseDestination -Force | Out-Null
        $sitePackages = Join-Path $projectRoot ".venv\Lib\site-packages"
        foreach ($distributionPattern in @(
            "pyside6-*.dist-info",
            "pyside6_essentials-*.dist-info",
            "pyside6_addons-*.dist-info",
            "shiboken6-*.dist-info",
            "pillow-*.dist-info",
            "pyinstaller-*.dist-info"
        )) {
            foreach ($distribution in @(
                Get-ChildItem -Path $sitePackages -Directory `
                    -Filter $distributionPattern -ErrorAction SilentlyContinue
            )) {
                $licenseSource = Join-Path $distribution.FullName "licenses"
                if (Test-Path -LiteralPath $licenseSource) {
                    $target = Join-Path $licenseDestination $distribution.Name
                    Copy-Item -LiteralPath $licenseSource -Destination $target `
                        -Recurse -Force
                }
            }
        }

        $pythonExecutable = Join-Path $projectRoot ".venv\Scripts\python.exe"
        $pythonBase = & $pythonExecutable -c "import sys; print(sys.base_prefix)"
        if ($LASTEXITCODE -ne 0) {
            throw "Cannot determine the Python base directory"
        }
        $pythonLicense = Join-Path ($pythonBase.Trim()) "LICENSE.txt"
        if (Test-Path -LiteralPath $pythonLicense) {
            Copy-Item -LiteralPath $pythonLicense -Destination (
                Join-Path $licenseDestination "Python-LICENSE.txt"
            ) -Force
        }

        if (Test-Path -LiteralPath (Join-Path $stagingResolved "settings.json")) {
            throw "The public archive must not contain settings.json"
        }

        $archiveName = "EaWFocusTextPreview-$version-windows-x64.zip"
        $archivePath = Join-Path $releaseRoot $archiveName
        $checksumPath = "$archivePath.sha256"
        Remove-Item -LiteralPath $archivePath -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $checksumPath -Force -ErrorAction SilentlyContinue

        Compress-Archive -Path (Join-Path $stagingResolved "*") `
            -DestinationPath $archivePath -CompressionLevel Optimal
        $hash = Get-FileHash -LiteralPath $archivePath -Algorithm SHA256
        "$($hash.Hash.ToLowerInvariant())  $archiveName" | Set-Content `
            -LiteralPath $checksumPath -Encoding ascii

        Write-Host ""
        Write-Host "Release archive: $archivePath"
        Write-Host "SHA-256:        $checksumPath"
    }
    finally {
        if (Test-Path -LiteralPath $stagingResolved) {
            Remove-Item -LiteralPath $stagingResolved -Recurse -Force
        }
    }
}
finally {
    Pop-Location
}
