# stop.ps1 - Gracefully stop all pipeline services and free ports
param (
    [switch]$Force
)

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  MULTI-AGENT PIPELINE - SHUTTING DOWN ALL SERVICES" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# Service ports to clean up
$ports = @(5173, 5678, 8010, 8011, 8012, 8013, 8014, 8015, 8020, 11434)

foreach ($port in $ports) {
    try {
        $pids = netstat -ano 2>$null | Select-String ":$port\s+" | Select-String "LISTENING" | ForEach-Object {
            $parts = ($_ -split "\s+") | Where-Object { $_ -ne "" }
            $parts[-1]
        } | Select-Object -Unique

        foreach ($p in $pids) {
            if ($p -and $p -ne "0") {
                Write-Host "  Stopping process $p on port :$port..." -ForegroundColor Yellow
                Stop-Process -Id ([int]$p) -Force -ErrorAction SilentlyContinue
            }
        }
    } catch {}
}

# Stop Docker n8n container if Docker is available
try {
    $dockerRunning = docker ps -q 2>$null
    if ($dockerRunning) {
        Write-Host "  Stopping Docker containers..." -ForegroundColor Yellow
        docker compose stop n8n 2>$null | Out-Null
    }
} catch {}

Start-Sleep -Seconds 1

Write-Host "============================================================" -ForegroundColor Green
Write-Host "  ALL PIPELINE SERVICES STOPPED SUCCESSFULLY" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
