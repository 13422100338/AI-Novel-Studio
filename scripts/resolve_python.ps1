function Resolve-ProjectPython {
    $projectRoot = Split-Path -Parent $PSScriptRoot
    $virtualEnvironment = Join-Path $projectRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $virtualEnvironment) {
        return (Resolve-Path -LiteralPath $virtualEnvironment).Path
    }

    # Linked worktrees share the main checkout's environment when they have none.
    if ((Test-Path -LiteralPath (Join-Path $projectRoot ".git")) -and
        (Get-Command git -ErrorAction SilentlyContinue)) {
        # Git emits UTF-8 paths even when Windows PowerShell uses an OEM codepage.
        $gitOutputEncoding = [Console]::OutputEncoding
        try {
            [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
            $commonDirectory = & git -C $projectRoot rev-parse --path-format=absolute --git-common-dir
            $gitExitCode = $LASTEXITCODE
        }
        finally {
            [Console]::OutputEncoding = $gitOutputEncoding
        }
        if ($gitExitCode -eq 0) {
            $sharedEnvironment = Join-Path (Split-Path -Parent $commonDirectory) ".venv\Scripts\python.exe"
            if (Test-Path -LiteralPath $sharedEnvironment) {
                return (Resolve-Path -LiteralPath $sharedEnvironment).Path
            }
        }
    }

    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        throw "Python was not found. Create .venv or add python to PATH."
    }
    return $command.Source
}
