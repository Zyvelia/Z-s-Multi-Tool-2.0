<#
    resolve_net_tools.ps1

    Looks up the current Npcap and Nmap Windows installer download URLs
    from their own release-archive pages, so install.iss can curl.exe
    them at install time instead of us hardcoding a version number that
    goes stale.

    Called by install.iss like:
        resolve_net_tools.ps1 -OutFile <path>

    Writes whichever of these it manages to resolve, one per line, to
    -OutFile (install.iss's [Code] section parses these exact prefixes):
        NPCAP_URL=<url>
        NMAP_URL=<url>

    A tool that fails to resolve is simply left out of the file rather
    than aborting the whole thing - install.iss only launches the
    installers it actually got a URL (and successful download) for, so
    a hiccup on one site shouldn't block the other.

    Always exits 0 unless it couldn't write -OutFile at all, matching
    install.iss's expectation (ResultCode <> 0 there means "treat the
    whole lookup as failed").

    Requires PowerShell 5+ (Invoke-WebRequest), which ships with
    Windows 10/11 by default.
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$OutFile
)

$ErrorActionPreference = "Stop"

function Resolve-LatestHref {
    param(
        [string]$IndexUrl,
        [string]$Pattern
    )
    try {
        $page = Invoke-WebRequest -Uri $IndexUrl -UseBasicParsing
        # Both dist/ pages list newest-first, so the first regex match
        # is the current release - same approach download_vlc.ps1 uses.
        $href = ($page.Links |
            Where-Object { $_.href -match $Pattern } |
            Select-Object -First 1).href
        if (-not $href) {
            Write-Host "[resolve_net_tools] No match for '$Pattern' at $IndexUrl"
            return $null
        }
        # Links are sometimes relative ("npcap-1.88.exe"), sometimes
        # absolute - normalize against the index page either way.
        return [System.Uri]::new([System.Uri]$IndexUrl, $href).AbsoluteUri
    } catch {
        Write-Host "[resolve_net_tools] Failed to read $IndexUrl - $($_.Exception.Message)"
        return $null
    }
}

$results = @()

# Npcap: e.g. "npcap-1.88.exe" - excludes npcap-*-debug.exe,
# npcap-*-DebugSymbols.zip, npcap-sdk-*.zip and the legacy
# npcap-nmap-*.exe bundle installers.
$npcapUrl = Resolve-LatestHref `
    -IndexUrl "https://npcap.com/dist/" `
    -Pattern '^npcap-[\d.]+\.exe$'
if ($npcapUrl) {
    Write-Host "[resolve_net_tools] Npcap -> $npcapUrl"
    $results += "NPCAP_URL=$npcapUrl"
}

# Nmap: e.g. "nmap-7.991-setup.exe" - the Windows self-installer only.
$nmapUrl = Resolve-LatestHref `
    -IndexUrl "https://nmap.org/dist/" `
    -Pattern '^nmap-[\d.]+-setup\.exe$'
if ($nmapUrl) {
    Write-Host "[resolve_net_tools] Nmap -> $nmapUrl"
    $results += "NMAP_URL=$nmapUrl"
}

try {
    Set-Content -Path $OutFile -Value $results -Encoding ASCII
} catch {
    Write-Host "[resolve_net_tools] Could not write $OutFile - $($_.Exception.Message)"
    exit 1
}

exit 0