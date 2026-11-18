# MathInk stop script (Windows PowerShell 5.1+)
# Gracefully stops the tray app, the server and llama-server.
# Usage: powershell -ExecutionPolicy Bypass -File .\stop.ps1
$port = if ($env:MATHINK_PORT) { $env:MATHINK_PORT } else { "8848" }
$root = $PSScriptRoot
$py = ".\.venv\Scripts\python.exe"
$stopped = 0

# 1) preferred: ask the launcher to stop its whole tree
if (Test-Path $py) {
    & $py launcher.py --stop 2>$null
}

# 2) kill anything still listening on the MathInk port
$listeners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
foreach ($c in $listeners) {
    try {
        Stop-Process -Id $c.OwningProcess -Force -ErrorAction Stop
        Write-Host "Stopped listener on port $port (PID $($c.OwningProcess))"
        $stopped++
    } catch {}
}

# 3) kill leftover uvicorn/app.main processes for this project
Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*uvicorn*app.main:app*" } |
    ForEach-Object {
        try {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop
            Write-Host "Stopped uvicorn (PID $($_.ProcessId))"
            $stopped++
        } catch {}
    }

# 4) kill the llama-server started by MathInk (matched by model path)
Get-CimInstance Win32_Process -Filter "Name='llama-server.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*$root\models\vlm*" -or $_.CommandLine -like "*models\vlm\model-q4km.gguf*" } |
    ForEach-Object {
        try {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop
            Write-Host "Stopped llama-server (PID $($_.ProcessId))"
            $stopped++
        } catch {}
    }

if ($stopped -eq 0) {
    Write-Host "MathInk is not running (port $port is free)."
} else {
    Write-Host "MathInk stopped; VRAM should be released."
}
