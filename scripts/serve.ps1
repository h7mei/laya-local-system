# Windows launcher for the one serve entry point (see serve.py).
# Usage: .\scripts\serve.ps1
#        .\scripts\serve.ps1 --download-only
#        .\scripts\serve.ps1 --check-only

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    Write-Error "Missing $Python. Create the venv and install deps first (see README.md)."
}

& $Python (Join-Path $PSScriptRoot "serve.py") @args
exit $LASTEXITCODE
