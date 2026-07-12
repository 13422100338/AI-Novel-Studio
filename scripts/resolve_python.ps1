function Resolve-ProjectPython {
    $projectRoot = Split-Path -Parent $PSScriptRoot
    $virtualEnvironment = Join-Path $projectRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $virtualEnvironment) {
        return (Resolve-Path -LiteralPath $virtualEnvironment).Path
    }

    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        throw "Python was not found. Create .venv or add python to PATH."
    }
    return $command.Source
}
