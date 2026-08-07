$ErrorActionPreference = "SilentlyContinue"

$TestUrl = "https://api.telegram.org"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$CacheDir = Join-Path $Root "data\bootstrap"
$CacheFile = Join-Path $CacheDir "network_route.json"
$NoProxy = "localhost,127.0.0.1,::1"

function Normalize-Proxy([string]$Value, [string]$Scheme = "http") {
    if ([string]::IsNullOrWhiteSpace($Value)) { return "" }
    $Value = $Value.Trim()
    if ($Value -notmatch "://") { return "$Scheme`://$Value" }
    if ($Value.StartsWith("socks5h://", [System.StringComparison]::OrdinalIgnoreCase)) {
        return "socks5://" + $Value.Substring(10)
    }
    return $Value
}

function Normalize-Bypass([string]$Raw) {
    $items = New-Object System.Collections.Generic.List[string]
    if (-not [string]::IsNullOrWhiteSpace($Raw)) {
        foreach ($item in ($Raw -split "[;,]")) {
            $value = $item.Trim()
            if (-not $value) { continue }
            if ($value.ToLowerInvariant() -eq "<local>") {
                $items.Add("localhost"); $items.Add("127.0.0.1"); $items.Add("::1")
            } else {
                $items.Add($value)
            }
        }
    }
    if ($items.Count -eq 0) {
        $items.Add("localhost"); $items.Add("127.0.0.1"); $items.Add("::1")
    }
    return (($items | Select-Object -Unique) -join ",")
}

function Get-DotEnvValue([string]$Name) {
    $Path = Join-Path $Root ".env"
    if (-not (Test-Path $Path)) { return "" }
    foreach ($line in Get-Content -LiteralPath $Path) {
        $trimmed = ([string]$line).Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#") -or $trimmed -notmatch "=") { continue }
        $pair = $trimmed -split "=", 2
        if ($pair[0].Trim().ToUpperInvariant() -eq $Name.ToUpperInvariant()) {
            return $pair[1].Trim().Trim('"').Trim("'")
        }
    }
    return ""
}

$candidates = New-Object System.Collections.ArrayList
$seen = @{}
function Add-Candidate([string]$Source, [string]$Url) {
    $normalized = Normalize-Proxy $Url "http"
    if (-not $normalized) { return }
    $key = $normalized.ToLowerInvariant()
    if ($seen.ContainsKey($key)) { return }
    $seen[$key] = $true
    [void]$candidates.Add([PSCustomObject]@{ Source = $Source; Url = $normalized })
}

function Test-Route([string]$ProxyUrl) {
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if (-not $curl) {
        # A listening local endpoint is a useful fallback when curl is unavailable.
        if ($ProxyUrl -match '^\w+://(127\.0\.0\.1|localhost):([0-9]+)') {
            try {
                $client = New-Object System.Net.Sockets.TcpClient
                $task = $client.ConnectAsync($Matches[1], [int]$Matches[2])
                if (-not $task.Wait(1200)) { $client.Dispose(); return $false }
                $client.Dispose(); return $true
            } catch { return $false }
        }
        return $true
    }

    $arguments = @("-sS", "-o", "NUL", "--connect-timeout", "4", "--max-time", "8", "-I")
    if ($ProxyUrl) { $arguments += @("--proxy", $ProxyUrl) }
    $arguments += $TestUrl
    & curl.exe @arguments 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

# Optional explicit override. AUTO/empty is direct-first.
# DIRECT/NONE/OFF forces direct networking and never enables a proxy.
$manual = Get-DotEnvValue "GAMEBOT_PROXY_URL"
$manualMode = ([string]$manual).Trim().ToLowerInvariant()
$forceDirect = $manualMode -in @("direct", "none", "off")
$explicitProxy = $manual -and $manualMode -notin @("auto", "direct", "none", "off")
if ($explicitProxy) {
    Add-Candidate "env-file" $manual
}

foreach ($name in @("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy")) {
    $value = [Environment]::GetEnvironmentVariable($name)
    if ($value) { Add-Candidate "environment" $value }
}

$reg = Get-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings"
$proxyOverride = ""
if ($reg) {
    $proxyOverride = [string]$reg.ProxyOverride
    if ([int]$reg.ProxyEnable -eq 1 -and -not [string]::IsNullOrWhiteSpace([string]$reg.ProxyServer)) {
        $raw = ([string]$reg.ProxyServer).Trim()
        if ($raw -notmatch "=") {
            Add-Candidate "windows-manual" $raw
        } else {
            foreach ($part in ($raw -split ";")) {
                if ($part -notmatch "=") { continue }
                $pair = $part -split "=", 2
                $kind = $pair[0].Trim().ToLowerInvariant()
                $value = $pair[1].Trim()
                if ($kind -eq "socks") { Add-Candidate "windows-manual-socks" (Normalize-Proxy $value "socks5") }
                elseif ($kind -in @("https", "http")) { Add-Candidate "windows-manual-$kind" $value }
            }
        }
    }
}

# Resolves Windows automatic/PAC settings specifically for Telegram.
try {
    $target = [Uri]$TestUrl
    $resolver = [System.Net.WebRequest]::GetSystemWebProxy()
    $resolver.Credentials = [System.Net.CredentialCache]::DefaultNetworkCredentials
    $resolved = $resolver.GetProxy($target)
    if ($resolved -and $resolved.AbsoluteUri -ne $target.AbsoluteUri) {
        Add-Candidate "windows-pac" $resolved.AbsoluteUri
    }
} catch {}

# WinHTTP proxy is separate from the normal Windows Internet Settings.
try {
    $winHttpText = (& netsh winhttp show proxy | Out-String)
    foreach ($match in [regex]::Matches($winHttpText, '(?i)(?:https?=)?((?:127\.0\.0\.1|localhost|[a-z0-9.-]+):[0-9]{2,5})')) {
        Add-Candidate "winhttp" $match.Groups[1].Value
    }
} catch {}

# Reuse the previous verified route first when it is still available.
if (Test-Path $CacheFile) {
    try {
        $cached = Get-Content -LiteralPath $CacheFile -Raw | ConvertFrom-Json
        if ($cached.proxy_url) { Add-Candidate "cached-$($cached.source)" ([string]$cached.proxy_url) }
    } catch {}
}

# Some VPN clients expose a local mixed/HTTP/SOCKS port without setting ProxyEnable.
$listenerPorts = @{}
try {
    foreach ($endpoint in [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()) {
        if ($endpoint.Address.ToString() -in @("127.0.0.1", "0.0.0.0", "::1", "::")) {
            $listenerPorts[[int]$endpoint.Port] = $true
        }
    }
} catch {}

$localCandidates = @(
    @{ Port = 7890; Schemes = @("http", "socks5") },
    @{ Port = 7891; Schemes = @("socks5", "http") },
    @{ Port = 7897; Schemes = @("http", "socks5") },
    @{ Port = 10809; Schemes = @("http") },
    @{ Port = 10808; Schemes = @("socks5", "http") },
    @{ Port = 2080; Schemes = @("socks5", "http") },
    @{ Port = 2081; Schemes = @("http", "socks5") },
    @{ Port = 1080; Schemes = @("socks5", "http") },
    @{ Port = 8080; Schemes = @("http") },
    @{ Port = 8118; Schemes = @("http") },
    @{ Port = 8888; Schemes = @("http") }
)
foreach ($entry in $localCandidates) {
    if (-not $listenerPorts.ContainsKey([int]$entry.Port)) { continue }
    foreach ($scheme in $entry.Schemes) {
        Add-Candidate "local-listener-$($entry.Port)" "$scheme`://127.0.0.1:$($entry.Port)"
    }
}

$selected = $null
$directWorks = $false

# Direct-first policy:
#   * direct/none/off -> direct only
#   * explicit proxy -> explicit proxy first, direct as fallback
#   * auto/empty -> direct first, detected proxy only if direct fails
if ($forceDirect) {
    $directWorks = Test-Route ""
} elseif ($explicitProxy) {
    foreach ($candidate in $candidates) {
        if (Test-Route ([string]$candidate.Url)) {
            $selected = $candidate
            break
        }
    }
    if (-not $selected) {
        $directWorks = Test-Route ""
    }
} else {
    $directWorks = Test-Route ""
    if (-not $directWorks) {
        foreach ($candidate in $candidates) {
            if (Test-Route ([string]$candidate.Url)) {
                $selected = $candidate
                break
            }
        }
    }
}

$source = "direct"
$proxyUrl = ""
$verified = $false
if ($directWorks) {
    $source = if ($forceDirect) { "direct-forced" } else { "direct-verified" }
    $verified = $true
} elseif ($selected) {
    $source = [string]$selected.Source
    $proxyUrl = [string]$selected.Url
    $verified = $true
} else {
    $source = if ($forceDirect) { "direct-forced-unverified" } else { "direct-unverified" }
}

try {
    New-Item -ItemType Directory -Force -Path $CacheDir | Out-Null
    [PSCustomObject]@{
        source = $source
        proxy_url = $proxyUrl
        verified = $verified
        updated_at = (Get-Date).ToString("o")
    } | ConvertTo-Json | Set-Content -LiteralPath $CacheFile -Encoding UTF8
} catch {}

$noProxy = Normalize-Bypass $proxyOverride
Write-Output "PROXY_SOURCE|$source"
Write-Output "PROXY_URL|$proxyUrl"
if ($proxyUrl) {
    Write-Output "HTTP_PROXY|$proxyUrl"
    Write-Output "HTTPS_PROXY|$proxyUrl"
    Write-Output "ALL_PROXY|$proxyUrl"
} else {
    Write-Output "HTTP_PROXY|"
    Write-Output "HTTPS_PROXY|"
    Write-Output "ALL_PROXY|"
}
Write-Output "NO_PROXY|$noProxy"
Write-Output "PROXY_VERIFIED|$($verified.ToString().ToLowerInvariant())"
