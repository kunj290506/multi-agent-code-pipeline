# Multi-Agent Pipeline — Start All Services (Windows PowerShell)
# Run this script from the repo root: .\scripts\start_all.ps1
#
# Prerequisites:
#   - Ollama installed and running on the host (http://localhost:11434)
#   - Python 3.11+ in PATH with all agent requirements installed
#   - Node.js 18+ in PATH (for webapp frontend)
#   - Docker Desktop running (for n8n)
#
# Each agent starts in a new PowerShell window.
# Close all windows to stop the services.

$RepoRoot = Split-Path -Parent $PSScriptRoot

Write-Host "Starting n8n (Docker)..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$RepoRoot'; docker compose up"

Start-Sleep -Seconds 3

Write-Host "Starting Target App (port 8000)..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$RepoRoot\target-app'; python -m uvicorn app:app --host 0.0.0.0 --port 8000 --reload"

Start-Sleep -Seconds 2

Write-Host "Starting Planner Agent (port 8010)..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$RepoRoot\planner-agent'; python -m uvicorn api:app --host 0.0.0.0 --port 8010 --reload"

Write-Host "Starting RAG Agent (port 8011)..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$RepoRoot\rag-agent'; python -m uvicorn api:app --host 0.0.0.0 --port 8011 --reload"

Write-Host "Starting DB Query Agent (port 8012)..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$RepoRoot\db-agent'; python -m uvicorn api:app --host 0.0.0.0 --port 8012 --reload"

Write-Host "Starting DB Executor Agent (port 8013)..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$RepoRoot\db-agent'; python -m uvicorn executor_api:app --host 0.0.0.0 --port 8013 --reload"

Write-Host "Starting CodeGen Agent (port 8014)..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$RepoRoot\codegen-agent'; python -m uvicorn api:app --host 0.0.0.0 --port 8014 --reload"

Write-Host "Starting Reviewer Agent (port 8015)..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$RepoRoot\reviewer-agent'; python -m uvicorn api:app --host 0.0.0.0 --port 8015 --reload"

Start-Sleep -Seconds 2

Write-Host "Starting Webapp Backend (port 8020)..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$RepoRoot\webapp\backend'; python -m uvicorn main:app --host 0.0.0.0 --port 8020 --reload"

Write-Host "Starting Webapp Frontend (port 5173)..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$RepoRoot\webapp\frontend'; npm run dev"

Write-Host ""
Write-Host "All services started." -ForegroundColor Green
Write-Host ""
Write-Host "Service URLs:" -ForegroundColor Yellow
Write-Host "  Target App:       http://localhost:8000/docs"
Write-Host "  Planner Agent:    http://localhost:8010/docs"
Write-Host "  RAG Agent:        http://localhost:8011/docs"
Write-Host "  DB Query Agent:   http://localhost:8012/docs"
Write-Host "  DB Executor:      http://localhost:8013/docs"
Write-Host "  CodeGen Agent:    http://localhost:8014/docs"
Write-Host "  Reviewer Agent:   http://localhost:8015/docs"
Write-Host "  Webapp Backend:   http://localhost:8020/docs"
Write-Host "  Webapp Frontend:  http://localhost:5173"
Write-Host "  n8n Dashboard:    http://localhost:5678  (admin / changeme)"
Write-Host ""
Write-Host "Run the evaluation: python eval/run_eval.py" -ForegroundColor Yellow
