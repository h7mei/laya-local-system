# Install CUDA-enabled PyTorch for this venv (NVIDIA GPU).
# Usage: .\scripts\setup-gpu.ps1
# Downloads the cu128 wheel with curl (more reliable than pip for ~2.7 GB),
# then installs it into .venv. Compatible with driver CUDA 12.x / RTX 50-series.

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    Write-Error "Missing $Python. Create the venv and install deps first (see README.md)."
}

$WheelDir = Join-Path $Root ".cache\wheels"
$WheelName = "torch-2.11.0+cu128-cp312-cp312-win_amd64.whl"
$WheelPath = Join-Path $WheelDir $WheelName
$WheelUrl = "https://download.pytorch.org/whl/cu128/torch-2.11.0%2Bcu128-cp312-cp312-win_amd64.whl"
$ExpectedBytes = 2753200000L  # ~2.56 GiB; allow small variance

New-Item -ItemType Directory -Force -Path $WheelDir | Out-Null

$needDownload = $true
if (Test-Path $WheelPath) {
    $size = (Get-Item $WheelPath).Length
    if ($size -gt ($ExpectedBytes * 0.98)) {
        Write-Host "Using cached wheel ($([math]::Round($size/1MB)) MB): $WheelPath"
        $needDownload = $false
    } else {
        Write-Host "Resuming incomplete wheel ($([math]::Round($size/1MB)) MB)..."
    }
}

if ($needDownload) {
    Write-Host "Downloading CUDA torch wheel (~2.6 GB). This can take a while..."
    & curl.exe -L --retry 20 --retry-all-errors --continue-at - `
        --connect-timeout 30 --speed-time 120 --speed-limit 5000 `
        -o $WheelPath $WheelUrl
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host "Uninstalling any existing torch..."
& $Python -m pip uninstall -y torch 2>$null

Write-Host "Installing from local wheel..."
& $Python -m pip install --force-reinstall $WheelPath
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Verifying CUDA..."
& $Python -c @"
import torch
print('torch', torch.__version__)
print('cuda_available', torch.cuda.is_available())
print('cuda', torch.version.cuda)
if torch.cuda.is_available():
    print('gpu', torch.cuda.get_device_name(0))
else:
    raise SystemExit('CUDA not available after install — check NVIDIA drivers.')
"@
exit $LASTEXITCODE
