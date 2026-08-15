<#
    download_vlc.ps1

    Fetches the latest official VLC win64 "portable" zip build from
    VideoLAN's own mirror and extracts it, so build.bat can bundle
    libvlc.dll / libvlccore.dll / plugins\ into dist\ even if the
    machine running the build doesn't have VLC installed system-wide.

    Prints a single line "VLC_DIR=<path>" on success so build.bat can
    capture it with a `for /f` loop. Any other output is just status
    logging to the console.

    Requires PowerShell 5+ (Expand-Archive), which ships with Windows
    10/11 by default.
#>

param(
    [string]$Destination = ".vlc_cache"
)

$ErrorActionPreference = "Stop"

try {
    $indexUrl = "https://download.videolan.org/pub/videolan/vlc/last/win64/"
    Write-Host "[download_vlc] Checking $indexUrl for the latest VLC win64 build..."

    $page = Invoke-WebRequest -Uri $indexUrl -UseBasicParsing

    $zipName = ($page.Links |
        Where-Object { $_.href -match '^vlc-.*-win64\.zip$' } |
        Select-Object -First 1).href

    if (-not $zipName) {
        Write-Host "[download_vlc] Could not find a win64 .zip build at $indexUrl"
        exit 1
    }

    New-Item -ItemType Directory -Force -Path $Destination | Out-Null

    $zipPath = Join-Path $Destination $zipName

    if (-not (Test-Path $zipPath)) {
        Write-Host "[download_vlc] Downloading $indexUrl$zipName ..."
        Invoke-WebRequest -Uri "$indexUrl$zipName" -OutFile $zipPath -UseBasicParsing
    } else {
        Write-Host "[download_vlc] $zipName already cached, skipping download."
    }

    $extractRoot = Join-Path $Destination ([IO.Path]::GetFileNameWithoutExtension($zipName))

    if (-not (Test-Path $extractRoot)) {
        Write-Host "[download_vlc] Extracting..."
        Expand-Archive -Path $zipPath -DestinationPath $Destination -Force
    }

    # The zip contains one top-level folder (e.g. vlc-3.0.20\) with
    # libvlc.dll, libvlccore.dll, and plugins\ directly inside it.
    if (-not (Test-Path (Join-Path $extractRoot "libvlc.dll"))) {
        Write-Host "[download_vlc] Extracted, but libvlc.dll wasn't where expected: $extractRoot"
        exit 1
    }

    Write-Host "[download_vlc] Ready at $extractRoot"
    # This is the line build.bat actually parses - keep it last and
    # exactly in this "VLC_DIR=<path>" form.
    Write-Host "VLC_DIR=$extractRoot"
    exit 0

} catch {
    Write-Host "[download_vlc] Failed: $($_.Exception.Message)"
    exit 1
}