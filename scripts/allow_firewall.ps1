# Allow MathInk through Windows Firewall for private LAN access.
# Must be run as Administrator:
#   powershell -ExecutionPolicy Bypass -File .\scripts\allow_firewall.ps1
$port = if ($env:MATHINK_PORT) { $env:MATHINK_PORT } else { "8848" }
$name = "MathInk $port"

$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "Please run this script as Administrator." -ForegroundColor Yellow
    exit 1
}

$existing = Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Firewall rule already exists: $name"
    exit 0
}

New-NetFirewallRule -DisplayName $name -Direction Inbound -Action Allow `
    -Protocol TCP -LocalPort $port -Profile Private | Out-Null
Write-Host "Added firewall rule: $name (TCP $port, Private profile)"
