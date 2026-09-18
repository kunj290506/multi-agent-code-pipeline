# Multi-Agent Pipeline — Start All Services (2 windows only)
# Run from the repo root: .\scripts\start_all.ps1
#
# Window 1 — Backend  : all 8 Python agents in one terminal via launch_backend.py
# Window 2 — Frontend : Vite dev server (npm run dev)
#
# Prerequisites:
#   - Python 3.11+ with all agent requirements installed
#   - Node.js 18+ with webapp/frontend node_modules installed
#   - Ollama running on the host (http://localhost:11434)  [optional for offline mode]

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
    -r "$RepoRoot\target-app\requirements.txt" `
    -q 2>$null

# ── Install frontend deps (silent, fast on repeat runs) ──────────────────────
Write-Host "[2/3] Installing frontend dependencies (skipped if up to date)..." -ForegroundColor Yellow
Push-Location "$RepoRoot\webapp\frontend"
npm install --silent 2>$null
Pop-Location

# ── Launch 2 windows ─────────────────────────────────────────────────────────
Write-Host "[3/3] Launching 2 terminal windows..." -ForegroundColor Yellow

# Window 1: all backend services in a single Python process
Start-Process powershell -ArgumentList `
    "-NoExit", `
    "-Command", `
    "Set-Location '$RepoRoot'; python scripts/launch_backend.py"

Start-Sleep -Seconds 5   # let agents bind ports before frontend starts

# Window 2: Vite frontend
Start-Process powershell -ArgumentList `
    "-NoExit", `
    "-Command", `
    "Set-Location '$RepoRoot\webapp\frontend'; npm run dev"

Start-Sleep -Seconds 3

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  ALL SERVICES STARTED (2 windows)" -ForegroundColor Green
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
Write-Host "    cd rag-agent; python ingest.py" -ForegroundColor Yellow
Write-Host ""

# Auto-open browser
Start-Process "http://localhost:5173"
