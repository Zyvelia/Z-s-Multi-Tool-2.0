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

    # NOTE: the zip is named "vlc-X.Y.Z-win64.zip" but the folder INSIDE
    # it is just "vlc-X.Y.Z" - no "-win64" suffix. Assuming the extracted
    # folder name matches the zip filename (as this used to) silently
    # looks in a path that doesn't exist. Instead, extract into its own
    # per-zip subfolder (so re-runs can still skip a repeat extract) and
    # search for libvlc.dll wherever VideoLAN actually put it - this
    # keeps working even if they change the internal layout again.
    $extractRoot = Join-Path $Destination ([IO.Path]::GetFileNameWithoutExtension($zipName))

    if (-not (Test-Path $extractRoot)) {
        Write-Host "[download_vlc] Extracting..."
        Expand-Archive -Path $zipPath -DestinationPath $extractRoot -Force
    }

    $libvlc = Get-ChildItem -Path $extractRoot -Filter "libvlc.dll" -Recurse -File -ErrorAction SilentlyContinue |
        Select-Object -First 1

    if (-not $libvlc) {
        Write-Host "[download_vlc] Extracted, but couldn't find libvlc.dll anywhere under: $extractRoot"
        exit 1
    }

    $extractRoot = $libvlc.DirectoryName

    Write-Host "[download_vlc] Ready at $extractRoot"
    # This is the line build.bat actually parses - keep it last and
    # exactly in this "VLC_DIR=<path>" form.
    Write-Host "VLC_DIR=$extractRoot"
    exit 0

} catch {
    Write-Host "[download_vlc] Failed: $($_.Exception.Message)"
    exit 1
}