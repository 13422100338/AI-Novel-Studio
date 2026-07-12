$ErrorActionPreference = "Stop"
. "$PSScriptRoot\resolve_python.ps1"
$Python = Resolve-ProjectPython
$projectRoot = Split-Path -Parent $PSScriptRoot

Push-Location $projectRoot
try {
    if (-not (Test-Path -LiteralPath ".privacy-blocklist")) {
        throw ".privacy-blocklist is required for release verification."
    }
    & $Python -m scripts.privacy_scan --root . --terms-file .privacy-blocklist --require-terms
    if ($LASTEXITCODE -ne 0) { throw "Source privacy scan failed with exit code $LASTEXITCODE." }
    & $Python -m scripts.privacy_scan --root dist --terms-file .privacy-blocklist --require-terms
    if ($LASTEXITCODE -ne 0) { throw "Distribution privacy scan failed with exit code $LASTEXITCODE." }
    $history = git log --all --format=fuller -p
    if ($LASTEXITCODE -ne 0) { throw "Git history scan failed with exit code $LASTEXITCODE." }
    $terms = Get-Content -LiteralPath ".privacy-blocklist" | Where-Object {
        $_.Trim() -and -not $_.Trim().StartsWith("#")
    }
    foreach ($term in $terms) {
        if ($history -match [regex]::Escape($term)) {
            throw "Private term found in Git history or commit metadata."
        }
    }
    Write-Host "Release privacy verification passed."
}
finally {
    Pop-Location
}
