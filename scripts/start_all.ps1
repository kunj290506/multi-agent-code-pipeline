# Multi-Agent Pipeline — Start All Services (2 windows only)
# Run from the repo root: .\scripts\start_all.ps1
#
# Window 1 — Backend  : all 8 Python agents in one terminal via launch_backend.py
#             launch_backend.py now handles port pre-flight (Fix 3) and sequential
#             health-polling (Fix 2) before reporting ready — no Sleep needed here.
# Window 2 — Frontend : Vite dev server (npm run dev)
#             Started only after the webapp backend (:8020/health) is confirmed up.
#
# Prerequisites:
#   - Python 3.11+ with all agent requirements installed
#   - Node.js 18+ with webapp/frontend node_modules installed
#   - Ollama running: docker compose up -d  (or host Ollama on :11434)

$RepoRoot = Split-Path -Parent $PSScriptRoot

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  MULTI-AGENT PIPELINE STARTUP" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# ── Install / verify Python deps (silent, fast on repeat runs) ───────────────
Write-Host ""
Write-Host "[1/3] Installing Python dependencies (skipped if already satisfied)..." -ForegroundColor Yellow
python -m pip install `
    -r "$RepoRoot\agents\planner\requirements.txt" `
    -r "$RepoRoot\agents\rag\requirements.txt" `
    -r "$RepoRoot\agents\codegen\requirements.txt" `
    -r "$RepoRoot\agents\reviewer\requirements.txt" `
    -r "$RepoRoot\agents\db\requirements.txt" `
    -r "$RepoRoot\webapp\backend\requirements.txt" `
    -q 2>$null

# ── Install frontend deps (silent, fast on repeat runs) ──────────────────────
Write-Host "[2/3] Installing frontend dependencies (skipped if up to date)..." -ForegroundColor Yellow
Push-Location "$RepoRoot\webapp\frontend"
npm install --silent 2>$null
Pop-Location

# ── Launch backend window (launch_backend.py does its own sequencing) ────────
Write-Host "[3/3] Launching backend window..." -ForegroundColor Yellow

Start-Process powershell -ArgumentList `
    "-NoExit", `
    "-Command", `
    "Set-Location '$RepoRoot'; python scripts/launch_backend.py"

# ── Wait for the webapp backend health endpoint before opening the frontend ───
# launch_backend.py already ensures agents are healthy before binding :8020,
# so polling :8020/health here is the correct gate — not a fixed sleep.
Write-Host "  Waiting for webapp backend (:8020) to be ready..." -ForegroundColor Yellow
$backendReady = $false
$deadline = (Get-Date).AddSeconds(120)
while ((Get-Date) -lt $deadline) {
    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:8020/health" `
                                  -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
        if ($resp.StatusCode -eq 200) {
            $backendReady = $true
            break
        }
    } catch { }
    Start-Sleep -Milliseconds 1000
}

if (-not $backendReady) {
    Write-Host ""
    Write-Host "ERROR: webapp backend (:8020) did not come up within 120s." -ForegroundColor Red
    Write-Host "Check the backend window for errors." -ForegroundColor Red
    Write-Host "The frontend will NOT be started." -ForegroundColor Red
    exit 1
}

Write-Host "  Backend healthy. Starting frontend..." -ForegroundColor Green

# Window 2: Vite frontend
Start-Process powershell -ArgumentList `
    "-NoExit", `
    "-Command", `
    "Set-Location '$RepoRoot\webapp\frontend'; npm run dev"

# Brief pause for Vite's dev server to bind before we open the browser.
Start-Sleep -Seconds 3

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  ALL SERVICES STARTED" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  MAIN UI        http://localhost:5173" -ForegroundColor White
Write-Host ""
Write-Host "  Agent APIs (Swagger):" -ForegroundColor Gray
Write-Host "    Target App      http://localhost:8000/docs" -ForegroundColor Gray
Write-Host "    Planner         http://localhost:8010/docs" -ForegroundColor Gray
Write-Host "    RAG             http://localhost:8011/docs" -ForegroundColor Gray
Write-Host "    DB Query        http://localhost:8012/docs" -ForegroundColor Gray
Write-Host "    DB Executor     http://localhost:8013/docs" -ForegroundColor Gray
Write-Host "    CodeGen         http://localhost:8014/docs" -ForegroundColor Gray
Write-Host "    Reviewer        http://localhost:8015/docs" -ForegroundColor Gray
Write-Host "    Webapp Backend  http://localhost:8020/docs" -ForegroundColor Gray
Write-Host ""
Write-Host "  FIRST-TIME ONLY: ingest docs into RAG vector store:" -ForegroundColor Yellow
Write-Host "    python agents/rag/ingest.py" -ForegroundColor Yellow
Write-Host ""

# Auto-open browser
Start-Process "http://localhost:5173"
