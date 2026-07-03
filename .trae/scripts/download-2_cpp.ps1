param(
    [string]$Owner = "nirvanafaith",
    [string]$Repo = "PDF-OCR",
    [string]$RemotePath = "2_cpp",
    [string]$Ref = "main",
    [string]$OutDir = "c:\Users\E-VR\Documents\trae_projects\横校\软件2_cpp",
    [string]$Token = $env:GITHUB_TOKEN
)
if ([string]::IsNullOrWhiteSpace($Token)) { throw "GITHUB_TOKEN is required" }

$headers = @{
    Authorization = "Bearer $Token"
    Accept = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
}
$baseApi = "https://api.github.com"
$ProgressPreference = 'SilentlyContinue'

function Invoke-GhApi($url) {
    $resp = Invoke-RestMethod -Uri $url -Headers $headers -Method GET
    return $resp
}

function Write-Base64ToFile($b64, $outPath) {
    $bytes = [Convert]::FromBase64String($b64)
    [IO.File]::WriteAllBytes($outPath, $bytes)
}

# 1) Fetch recursive tree
$treeUrl = "$baseApi/repos/$Owner/$Repo/git/trees/${Ref}?recursive=1"
Write-Host "Fetching tree: $treeUrl"
$tree = Invoke-GhApi $treeUrl
if ($tree.truncated) {
    Write-Warning "Tree truncated; use contents API fallback"
}

$prefix = "$RemotePath/"
$entries = $tree.tree | Where-Object { $_.path.StartsWith($prefix) -and $_.type -eq "blob" }
Write-Host "Files to download: $($entries.Count)"

$stats = [PSCustomObject]@{ downloaded = 0; bytes = 0; errors = [System.Collections.Generic.List[string]]::new() }

# 2) Clean and recreate target root
if (Test-Path $OutDir) { Remove-Item $OutDir -Recurse -Force }
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null

# 3) Download each blob
foreach ($entry in $entries) {
    $relative = $entry.path.Substring($prefix.Length).Replace('/', '\')
    $localPath = Join-Path $OutDir $relative
    $dir = Split-Path $localPath -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    try {
        $blob = Invoke-GhApi "$baseApi/repos/$Owner/$Repo/git/blobs/$($entry.sha)"
        Write-Base64ToFile $blob.content $localPath
        $stats.downloaded++
        $stats.bytes += $blob.size
        Write-Host "OK  $($entry.path)"
    } catch {
        $msg = "FAIL $($entry.path): $_"
        Write-Warning $msg
        $stats.errors.Add($msg)
    }
}

$stats | Format-List
if ($stats.errors.Count -gt 0) { throw "Download failed with $($stats.errors.Count) error(s)" }
Write-Host "Download complete: $($stats.downloaded) files, $($stats.bytes) bytes"
