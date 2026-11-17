# MathInk launcher (Windows PowerShell 5.1+)
# Usage: powershell -ExecutionPolicy Bypass -File .\start.ps1
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
Write-Host "MathInk host:  http://127.0.0.1:$port"
Write-Host "Tablet pad:    http://<LAN-IP>:$port/pad  (the host page shows a QR code)"
Write-Host "Press Ctrl+C to stop."
$env:PYTHONPATH = "backend"
& $py -m uvicorn app.main:app --host 0.0.0.0 --port $port
