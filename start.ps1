# MathInk 本地开发/运行脚本（Windows PowerShell）
# 用法：powershell -ExecutionPolicy Bypass -File start.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "创建虚拟环境 .venv ..."
    python -m venv .venv
    & $py -m pip install --upgrade pip -q
    & $py -m pip install -r backend\requirements.txt -q
}

if (-not (Test-Path "models\comer\encoder_int8.onnx")) {
    Write-Host "下载模型 ..."
    & $py scripts\download_models.py --engine comer
}

$port = if ($env:MATHINK_PORT) { $env:MATHINK_PORT } else { "8848" }
Write-Host "启动 MathInk: http://127.0.0.1:$port"
$env:PYTHONPATH = "backend"
& $py -m uvicorn app.main:app --host 127.0.0.1 --port $port
