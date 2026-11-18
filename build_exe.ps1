# Build MathInk.exe (single-file, tray launcher).
# Usage: powershell -ExecutionPolicy Bypass -File .\build_exe.ps1 [-Clean]
param([switch]$Clean)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "Creating virtual environment .venv ..."
    python -m venv .venv
    & $py -m pip install --upgrade pip -q
    & $py -m pip install -r backend\requirements.txt -q
}

& $py -m pip install pyinstaller -q
& $py scripts\make_icon.py

if ($Clean) {
    Remove-Item build, dist -Recurse -Force -ErrorAction SilentlyContinue
}

& $py -m PyInstaller MathInk.spec --noconfirm --clean
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

Write-Host ""
Write-Host "Built: $PSScriptRoot\dist\MathInk.exe"
Write-Host "Place MathInk.exe next to models\ and tools\ (or run it in this folder)."
