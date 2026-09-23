# start_groq.ps1 — Launch the full multi-agent pipeline using Groq as the LLM backend.
# Run from the repo root:  .\scripts\start_groq.ps1
#
# Set your Groq API key before running:
#   $env:GROQ_API_KEY = "gsk_..."
# Or add it to your system/user environment variables.

$RepoRoot = Split-Path -Parent $PSScriptRoot

#  Environment 
$env:LLM_PROVIDER = "groq"
$env:GROQ_MODEL   = "qwen/qwen3.8-27b"

# Load from .env if it exists
if (Test-Path "$RepoRoot\.env") {
    Get-Content "$RepoRoot\.env" | Where-Object { $_ -match "^[^#=]+=" } | ForEach-Object {
        $name, $value = $_ -split '=', 2
        [Environment]::SetEnvironmentVariable($name.Trim(), $value.Trim())
    }
}

# Use key from environment if already set; otherwise prompt.
if (-not $env:GROQ_API_KEY) {
    $env:GROQ_API_KEY = Read-Host "Enter your GROQ_API_KEY"
}
if (-not $env:GROQ_API_KEY) {
    Write-Host "ERROR: GROQ_API_KEY is required." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  MULTI-AGENT PIPELINE  (Groq backend)" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  LLM_PROVIDER : $env:LLM_PROVIDER" -ForegroundColor Yellow
Write-Host "  GROQ_MODEL   : $env:GROQ_MODEL" -ForegroundColor Yellow
Write-Host ""

#  Kill anything still on agent ports 
foreach ($port in @(5173,8010,8011,8012,8013,8014,8015,8020)) {
    $targetPid = (netstat -ano 2>$null | Select-String ":$port " | Select-String "LISTENING" | ForEach-Object { ($_ -split "\s+")[-1] } | Select-Object -First 1)
    if ($targetPid) { taskkill /F /PID $targetPid 2>$null | Out-Null }
}
Start-Sleep -Seconds 1

#  Backend window 
Write-Host "[1/2] Starting backend services..." -ForegroundColor Yellow
$key = $env:GROQ_API_KEY
$model = $env:GROQ_MODEL
Start-Process powershell -ArgumentList "-NoExit", "-Command",
    "`$env:LLM_PROVIDER='groq'; `$env:GROQ_API_KEY='$key'; `$env:GROQ_MODEL='$model'; Set-Location '$RepoRoot'; python scripts/launch_backend.py"

#  Wait for webapp backend health 
Write-Host "  Waiting for backend (:8020)..." -ForegroundColor Yellow
$ready = $false
$deadline = (Get-Date).AddSeconds(300)
while ((Get-Date) -lt $deadline) {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:8020/health" -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
        if ($r.StatusCode -eq 200) { $ready = $true; break }
    } catch {}
    Start-Sleep -Milliseconds 1500
}

if (-not $ready) {
    Write-Host "ERROR: backend did not start within 300s. Check the backend window." -ForegroundColor Red
    exit 1
}
Write-Host "  Backend healthy." -ForegroundColor Green

#  Frontend window 
Write-Host "[2/2] Starting frontend (Vite)..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command",
    "Set-Location '$RepoRoot\webapp\frontend'; npm run dev -- --host"

Start-Sleep -Seconds 3

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  ALL SERVICES RUNNING" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  APP UI          http://localhost:5173" -ForegroundColor White
Write-Host "  Backend API     http://localhost:8020/docs" -ForegroundColor Gray
Write-Host ""
Write-Host "  Sample prompts to try:" -ForegroundColor Cyan
Write-Host "    - I want a simple calculator web app" -ForegroundColor White
Write-Host "    - Generate a REST endpoint to search tasks by project name" -ForegroundColor White
Write-Host "    - List all open tasks assigned to a specific user" -ForegroundColor White
Write-Host "    - Generate a React task card component" -ForegroundColor White
Write-Host ""

Start-Process "http://localhost:5173"
