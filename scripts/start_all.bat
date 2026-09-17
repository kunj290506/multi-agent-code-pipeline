@echo off
setlocal enabledelayedexpansion

:: ============================================================
::  Multi-Agent Pipeline — Start All Services
::  Double-click this file or run it from the repo root.
::  Each service opens in its own cmd window.
::  All windows can be closed individually or via Task Manager.
:: ============================================================

:: Resolve repo root (parent of the scripts\ folder this bat lives in)
set "ROOT=%~dp0.."
pushd "%ROOT%"
set "ROOT=%CD%"
popd

echo.
echo ============================================================
echo  MULTI-AGENT CODE PIPELINE — STARTUP
echo ============================================================
echo  Repo root: %ROOT%
echo.

:: ── 0. Check prerequisites ────────────────────────────────────

echo [CHECK] Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python not found. Install Python 3.11+ and add it to PATH.
    pause
    exit /b 1
)

echo [CHECK] Node.js...
node --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Node.js not found. Install Node.js 18+ and add it to PATH.
    pause
    exit /b 1
)

echo [CHECK] Docker...
docker --version >nul 2>&1
if errorlevel 1 (
    echo  WARNING: Docker not found. n8n will not start.
    echo  Install Docker Desktop from https://www.docker.com/
) else (
    echo [CHECK] Docker OK
)

echo [CHECK] Ollama...
curl -s http://localhost:11434/api/tags >nul 2>&1
if errorlevel 1 (
    echo  WARNING: Ollama is not running on port 11434.
    echo  Start Ollama from the system tray or run: ollama serve
    echo  Agents will start but LLM calls will fail until Ollama is up.
) else (
    echo [CHECK] Ollama OK
)

echo.
echo ── Installing Python dependencies (first run only) ─────────
echo.

pip install -r "%ROOT%\planner-agent\requirements.txt"  --quiet
pip install -r "%ROOT%\rag-agent\requirements.txt"      --quiet
pip install -r "%ROOT%\codegen-agent\requirements.txt"  --quiet
pip install -r "%ROOT%\reviewer-agent\requirements.txt" --quiet
pip install -r "%ROOT%\db-agent\requirements.txt"       --quiet
pip install -r "%ROOT%\webapp\backend\requirements.txt" --quiet
pip install -r "%ROOT%\target-app\requirements.txt"     --quiet

echo.
echo ── Installing frontend dependencies (first run only) ───────
echo.
cd /d "%ROOT%\webapp\frontend"
call npm install --silent
cd /d "%ROOT%"

echo.
echo ── Starting services ────────────────────────────────────────
echo.

:: ── 1. n8n (Docker) ──────────────────────────────────────────
echo [1/10] n8n (port 5678)...
start "n8n" cmd /k "cd /d "%ROOT%" && docker compose up"
timeout /t 4 /nobreak >nul

:: ── 2. Target App ────────────────────────────────────────────
echo [2/10] Target App (port 8000)...
start "Target App :8000" cmd /k "cd /d "%ROOT%\target-app" && python -m uvicorn app:app --host 0.0.0.0 --port 8000 --reload"
timeout /t 2 /nobreak >nul

:: ── 3. Planner Agent ─────────────────────────────────────────
echo [3/10] Planner Agent (port 8010)...
start "Planner :8010" cmd /k "cd /d "%ROOT%\planner-agent" && python -m uvicorn api:app --host 0.0.0.0 --port 8010 --reload"

:: ── 4. RAG Agent ─────────────────────────────────────────────
echo [4/10] RAG Agent (port 8011)...
start "RAG :8011" cmd /k "cd /d "%ROOT%\rag-agent" && python -m uvicorn api:app --host 0.0.0.0 --port 8011 --reload"

:: ── 5. DB Query Agent ────────────────────────────────────────
echo [5/10] DB Query Agent (port 8012)...
start "DB Query :8012" cmd /k "cd /d "%ROOT%\db-agent" && python -m uvicorn api:app --host 0.0.0.0 --port 8012 --reload"

:: ── 6. DB Executor Agent ─────────────────────────────────────
echo [6/10] DB Executor Agent (port 8013)...
start "DB Executor :8013" cmd /k "cd /d "%ROOT%\db-agent" && python -m uvicorn executor_api:app --host 0.0.0.0 --port 8013 --reload"

:: ── 7. CodeGen Agent ─────────────────────────────────────────
echo [7/10] CodeGen Agent (port 8014)...
start "CodeGen :8014" cmd /k "cd /d "%ROOT%\codegen-agent" && python -m uvicorn api:app --host 0.0.0.0 --port 8014 --reload"

:: ── 8. Reviewer Agent ────────────────────────────────────────
echo [8/10] Reviewer Agent (port 8015)...
start "Reviewer :8015" cmd /k "cd /d "%ROOT%\reviewer-agent" && python -m uvicorn api:app --host 0.0.0.0 --port 8015 --reload"

timeout /t 3 /nobreak >nul

:: ── 9. Webapp Backend ────────────────────────────────────────
echo [9/10] Webapp Backend (port 8020)...
start "Webapp Backend :8020" cmd /k "cd /d "%ROOT%\webapp\backend" && python -m uvicorn main:app --host 0.0.0.0 --port 8020 --reload"

timeout /t 2 /nobreak >nul

:: ── 10. Webapp Frontend ──────────────────────────────────────
echo [10/10] Webapp Frontend (port 5173)...
start "Webapp Frontend :5173" cmd /k "cd /d "%ROOT%\webapp\frontend" && npm run dev"

:: ── Wait for frontend to bind ────────────────────────────────
timeout /t 5 /nobreak >nul

:: ── Print all links ──────────────────────────────────────────
echo.
echo ============================================================
echo  ALL SERVICES STARTED — YOUR LINKS
echo ============================================================
echo.
echo   MAIN DASHBOARD (open this first)
echo   http://localhost:5173
echo.
echo   AGENT APIs (Swagger docs)
echo   Planner Agent    http://localhost:8010/docs
echo   RAG Agent        http://localhost:8011/docs
echo   DB Query Agent   http://localhost:8012/docs
echo   DB Executor      http://localhost:8013/docs
echo   CodeGen Agent    http://localhost:8014/docs
echo   Reviewer Agent   http://localhost:8015/docs
echo   Webapp Backend   http://localhost:8020/docs
echo   Target App       http://localhost:8000/docs
echo.
echo   ORCHESTRATION
echo   n8n Dashboard    http://localhost:5678
echo   n8n login:       admin / changeme
echo.
echo ============================================================
echo.
echo   FIRST-TIME SETUP (run once after this window opens):
echo   1. Ingest codebase into RAG vector store:
echo      cd rag-agent ^&^& python ingest.py
echo.
echo   2. Run the evaluation set:
echo      python eval/run_eval.py
echo ============================================================
echo.

:: ── Auto-open the dashboard in the default browser ───────────
timeout /t 2 /nobreak >nul
start http://localhost:5173

echo  Browser opening http://localhost:5173 ...
echo  Close this window whenever you like — services keep running.
echo.
pause
