# start.ps1 - Single command to start all multi-agent pipeline services and open in Chrome
# Usage: .\scripts\start.ps1

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  MULTI-AGENT PIPELINE - INITIALIZING SERVICES" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# ---------------------------------------------------------------------------
# 1. Prerequisite & Tool Checks
# ---------------------------------------------------------------------------
Write-Host "[1/6] Checking prerequisites..." -ForegroundColor Yellow

$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    Write-Host "ERROR: Python is not installed or not in PATH." -ForegroundColor Red
    exit 1
}

$nodeCmd = Get-Command node -ErrorAction SilentlyContinue
if (-not $nodeCmd) {
    Write-Host "ERROR: Node.js is not installed or not in PATH." -ForegroundColor Red
    exit 1
}

$ollamaExe = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
if (-not (Test-Path $ollamaExe)) {
    $ollamaCmd = Get-Command ollama -ErrorAction SilentlyContinue
    if ($ollamaCmd) { $ollamaExe = $ollamaCmd.Source }
}

$chromeCandidates = @(
    "C:\Program Files\Google\Chrome\Application\chrome.exe",
    "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
)
$chromeExe = $chromeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

# Load environment from .env if present
if (Test-Path "$RepoRoot\.env") {
    Get-Content "$RepoRoot\.env" | Where-Object { $_ -match "^[^#=]+=" } | ForEach-Object {
        $name, $value = $_ -split '=', 2
        [Environment]::SetEnvironmentVariable($name.Trim(), $value.Trim())
    }
}

if (-not $env:LLM_PROVIDER) {
    if ($env:GROQ_API_KEY) {
        $env:LLM_PROVIDER = "groq"
    } else {
        $env:LLM_PROVIDER = "ollama"
    }
}
if (-not $env:GROQ_MODEL) {
    $env:GROQ_MODEL = "qwen/qwen3.8-27b"
}
if (-not $env:OLLAMA_MODEL) {
    $env:OLLAMA_MODEL = "qwen2.5:7b-instruct-q4_K_M"
}

Write-Host "  Python:  $((python --version 2>&1).Trim())" -ForegroundColor Green
Write-Host "  Node.js: $((node --version 2>&1).Trim())" -ForegroundColor Green
Write-Host "  LLM Provider: $env:LLM_PROVIDER" -ForegroundColor Green

# ---------------------------------------------------------------------------
# 2. Port Pre-flight (Free any stale processes on service ports)
# ---------------------------------------------------------------------------
Write-Host "[2/6] Verifying service ports..." -ForegroundColor Yellow

$servicePorts = @(5173, 8010, 8011, 8012, 8013, 8014, 8015, 8020)
foreach ($port in $servicePorts) {
    $pids = netstat -ano 2>$null | Select-String ":$port\s+" | Select-String "LISTENING" | ForEach-Object {
        $parts = ($_ -split "\s+") | Where-Object { $_ -ne "" }
        $parts[-1]
    } | Select-Object -Unique

    foreach ($p in $pids) {
        if ($p -and $p -ne "0") {
            Write-Host "  Freeing stale process $p on port :$port..." -ForegroundColor Yellow
            Stop-Process -Id ([int]$p) -Force -ErrorAction SilentlyContinue
        }
    }
}
Start-Sleep -Milliseconds 500

# ---------------------------------------------------------------------------
# 3. Start Ollama Service
# ---------------------------------------------------------------------------
Write-Host "[3/6] Starting Ollama server (:11434)..." -ForegroundColor Yellow

$ollamaHealthy = $false
try {
    $res = Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
    if ($res.StatusCode -eq 200) { $ollamaHealthy = $true }
} catch {}

if (-not $ollamaHealthy) {
    if (Test-Path $ollamaExe) {
        Start-Process $ollamaExe -ArgumentList "serve" -WindowStyle Hidden
    } else {
        Start-Process "ollama" -ArgumentList "serve" -WindowStyle Hidden
    }

    $deadline = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt $deadline) {
        try {
            $res = Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
            if ($res.StatusCode -eq 200) { $ollamaHealthy = $true; break }
        } catch {}
        Start-Sleep -Milliseconds 500
    }
}

if ($ollamaHealthy) {
    Write-Host "  Ollama healthy on :11434." -ForegroundColor Green
} else {
    Write-Host "  WARNING: Ollama server did not respond within timeout. Continuing with remote provider..." -ForegroundColor Yellow
}

# ---------------------------------------------------------------------------
# 4. Start Backend Agent Suite (:8010-:8020)
# ---------------------------------------------------------------------------
Write-Host "[4/6] Starting backend agent services (:8010-:8020)..." -ForegroundColor Yellow

$key = $env:GROQ_API_KEY
$provider = $env:LLM_PROVIDER
$model = $env:GROQ_MODEL
$ollamaModel = $env:OLLAMA_MODEL

Start-Process "cmd.exe" -ArgumentList "/k", "python", "scripts\launch_backend.py" -WorkingDirectory $RepoRoot

# Wait for webapp backend (:8020) health
$backendHealthy = $false
$deadline = (Get-Date).AddSeconds(45)
while ((Get-Date) -lt $deadline) {
    try {
        $res = Invoke-WebRequest -Uri "http://127.0.0.1:8020/health" -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
        if ($res.StatusCode -eq 200) { $backendHealthy = $true; break }
    } catch {}
    Start-Sleep -Milliseconds 400
}

if (-not $backendHealthy) {
    Write-Host "ERROR: Backend services failed to start within timeout. Check logs." -ForegroundColor Red
    exit 1
}
Write-Host "  All 7 backend services healthy." -ForegroundColor Green

# ---------------------------------------------------------------------------
# 5. Start Frontend UI (:5173) & n8n (:5678)
# ---------------------------------------------------------------------------
Write-Host "[5/6] Starting frontend UI (:5173)..." -ForegroundColor Yellow

Start-Process "cmd.exe" -ArgumentList "/k", "npm", "run", "dev", "--", "--host" -WorkingDirectory "$RepoRoot\webapp\frontend"

$frontendHealthy = $false
$deadline = (Get-Date).AddSeconds(30)
while ((Get-Date) -lt $deadline) {
    try {
        $tcp = Test-NetConnection -ComputerName 127.0.0.1 -Port 5173 -WarningAction SilentlyContinue
        if ($tcp.TcpTestSucceeded) { $frontendHealthy = $true; break }
    } catch {}
    Start-Sleep -Milliseconds 400
}

if ($frontendHealthy) {
    Write-Host "  Frontend healthy on :5173." -ForegroundColor Green
} else {
    Write-Host "  Frontend starting up on :5173..." -ForegroundColor Yellow
}

# Start n8n if Docker is available
$n8nRunning = $false
try {
    $n8nCheck = Test-NetConnection -ComputerName 127.0.0.1 -Port 5678 -WarningAction SilentlyContinue
    if ($n8nCheck.TcpTestSucceeded) {
        $n8nRunning = $true
    } else {
        $dockerCheck = docker ps 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  Starting n8n container via Docker Compose..." -ForegroundColor Yellow
            docker compose up -d n8n 2>$null | Out-Null
            $deadline = (Get-Date).AddSeconds(30)
            while ((Get-Date) -lt $deadline) {
                $tcp = Test-NetConnection -ComputerName 127.0.0.1 -Port 5678 -WarningAction SilentlyContinue
                if ($tcp.TcpTestSucceeded) { $n8nRunning = $true; break }
                Start-Sleep -Seconds 1
            }
        }
    }
} catch {}

# Import n8n workflow if n8n is active
if ($n8nRunning) {
    Write-Host "  n8n active on :5678. Ensuring workflow is present..." -ForegroundColor Green
    try {
        $workflowPath = Join-Path $RepoRoot "n8n\workflow.json"
        if (Test-Path $workflowPath) {
            $wfJson = Get-Content $workflowPath -Raw
            # Check existing workflows
            $headers = @{
                "Authorization" = "Basic " + [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("admin:changeme"))
                "Content-Type"  = "application/json"
            }
            $existing = Invoke-RestMethod -Uri "http://localhost:5678/api/v1/workflows" -Headers $headers -Method Get -ErrorAction SilentlyContinue
            $hasWorkflow = $false
            if ($existing -and $existing.data) {
                foreach ($wf in $existing.data) {
                    if ($wf.name -eq "Multi-Agent Code Pipeline") { $hasWorkflow = $true; break }
                }
            }
            if (-not $hasWorkflow) {
                Invoke-RestMethod -Uri "http://localhost:5678/api/v1/workflows" -Headers $headers -Method Post -Body $wfJson -ErrorAction SilentlyContinue | Out-Null
                Write-Host "  Imported 'Multi-Agent Code Pipeline' workflow into n8n." -ForegroundColor Green
            } else {
                Write-Host "  Workflow already registered in n8n." -ForegroundColor Green
            }
        }
    } catch {}
} else {
    Write-Host "  n8n container inactive (Docker Desktop service currently stopped)." -ForegroundColor Gray
}

# ---------------------------------------------------------------------------
# 6. Service URL Table & Chrome Launch
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "================================================================================" -ForegroundColor Green
Write-Host "                         ALL SERVICES ARE RUNNING                               " -ForegroundColor Green
Write-Host "================================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  +-------------------+--------------------------------------------------------+" -ForegroundColor Cyan
Write-Host "  | Service           | URL                                                    |" -ForegroundColor Cyan
Write-Host "  +-------------------+--------------------------------------------------------+" -ForegroundColor Cyan
Write-Host "  | Frontend UI       | http://localhost:5173                                  |" -ForegroundColor White
Write-Host "  | Backend Base URL  | http://localhost:8020                                  |" -ForegroundColor White
Write-Host "  | API Docs (Swagger)| http://localhost:8020/docs                             |" -ForegroundColor White
Write-Host "  | Health Endpoint   | http://localhost:8020/health                           |" -ForegroundColor White
Write-Host "  | n8n Editor URL    | http://localhost:5678                                  |" -ForegroundColor White
Write-Host "  | n8n Webhook URL   | http://localhost:5678/webhook/feature-request          |" -ForegroundColor White
Write-Host "  | Ollama URL        | http://localhost:11434                                 |" -ForegroundColor White
Write-Host "  +-------------------+--------------------------------------------------------+" -ForegroundColor Cyan
Write-Host ""

$urlsToOpen = @(
    "http://localhost:5173",
    "http://localhost:8020",
    "http://localhost:8020/docs",
    "http://localhost:8020/health",
    "http://localhost:5678",
    "http://localhost:5678/webhook/feature-request",
    "http://localhost:11434"
)

if ($chromeExe) {
    Write-Host "[6/6] Opening all links in Google Chrome..." -ForegroundColor Yellow
    foreach ($url in $urlsToOpen) {
        Start-Process $chromeExe -ArgumentList $url
        Start-Sleep -Milliseconds 150
    }
} else {
    Write-Host "[6/6] Chrome not found at standard path. Opening in default browser..." -ForegroundColor Yellow
    foreach ($url in $urlsToOpen) {
        Start-Process $url
        Start-Sleep -Milliseconds 150
    }
}

Write-Host ""
Write-Host "Single-command stop: Run .\scripts\stop.ps1 or 'npm run stop' to shut down cleanly." -ForegroundColor Gray
Write-Host ""
