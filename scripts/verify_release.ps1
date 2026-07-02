$ErrorActionPreference = "Stop"
if (-not (Test-Path -LiteralPath ".privacy-blocklist")) {
    throw ".privacy-blocklist is required for release verification."
}
python -m scripts.privacy_scan --root . --terms-file .privacy-blocklist --require-terms
python -m scripts.privacy_scan --root dist --terms-file .privacy-blocklist --require-terms
$history = git log --all --format=fuller -p
$terms = Get-Content -LiteralPath ".privacy-blocklist" | Where-Object {
    $_.Trim() -and -not $_.Trim().StartsWith("#")
}
foreach ($term in $terms) {
    if ($history -match [regex]::Escape($term)) {
        throw "Private term found in Git history or commit metadata."
    }
}
Write-Host "Release privacy verification passed."
