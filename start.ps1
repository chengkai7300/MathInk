# MathInk launcher (Windows PowerShell 5.1+)
# Starts the tray app; it runs the server in the background and owns llama-server.
# Usage: powershell -ExecutionPolicy Bypass -File .\start.ps1
#        powershell -ExecutionPolicy Bypass -File .\start.ps1 -Console
param([switch]$Console)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "Creating virtual environment .venv ..."
    python -m venv .venv
    & $py -m pip install --upgrade pip -q
    & $py -m pip install -r backend\requirements.txt -q
}

if (-not (Test-Path "models\comer\encoder_int8.onnx")) {
    Write-Host "Downloading CoMER model ..."
    & $py scripts\download_models.py --engine comer
}

if (-not (Test-Path "models\vlm\model-q4km.gguf")) {
    Write-Host "VLM model not installed; CoMER only."
    Write-Host "Install with: .\.venv\Scripts\python scripts\download_models.py --engine vlm --llama"
}

$port = if ($env:MATHINK_PORT) { $env:MATHINK_PORT } else { "8848" }
$hostUrl = "http://127.0.0.1:$port"

function Test-Running {
    try {
        $r = Invoke-RestMethod "$hostUrl/api/health" -TimeoutSec 2
        return $true
    } catch {
        return $false
    }
}

if (Test-Running) {
    Write-Host "MathInk is already running: $hostUrl"
    Start-Process $hostUrl
    exit 0
}

if ($Console) {
    Write-Host "MathInk (console mode): $hostUrl"
    Write-Host "Press Ctrl+C to stop."
    $env:PYTHONPATH = "backend"
    & $py launcher.py
    exit $LASTEXITCODE
}

$pythonw = ".\.venv\Scripts\pythonw.exe"
if (-not (Test-Path $pythonw)) { $pythonw = $py }
Start-Process -FilePath $pythonw -ArgumentList "launcher.py" -WorkingDirectory $PSScriptRoot -WindowStyle Hidden

for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 500
    if (Test-Running) {
        Write-Host "MathInk is running: $hostUrl"
        Write-Host "Look for the MathInk icon in the notification area (system tray)."
        Write-Host "Right-click it to open the UI, copy the tablet URL, release VRAM, or quit."
        exit 0
    }
}

Write-Host "MathInk did not become ready. Check logs\launcher.log."
exit 1
