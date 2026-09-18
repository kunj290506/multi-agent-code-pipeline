@echo off
setlocal enabledelayedexpansion

:: ============================================================
::  Multi-Agent Pipeline — Start All Services (2 windows only)
::  Window 1: all Python backend agents via launch_backend.py
::  Window 2: Vite frontend (npm run dev)
:: ============================================================

set "ROOT=%~dp0.."
pushd "%ROOT%"
set "ROOT=%CD%"
popd

echo.
echo ============================================================
echo  MULTI-AGENT CODE PIPELINE STARTUP
echo ============================================================
echo  Repo root: %ROOT%
echo.

:: ── Prerequisites check ────────────────────────────────────
echo [CHECK] Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python not found. Install Python 3.11+ and add it to PATH.
    pause & exit /b 1
)

echo [CHECK] Node.js...
node --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Node.js not found. Install Node.js 18+ and add it to PATH.
    pause & exit /b 1
)

:: ── Install Python deps (fast / silent on repeat runs) ─────
echo.
echo [1/3] Installing Python dependencies...
python -m pip install ^
    -r "%ROOT%\agents\planner\requirements.txt" ^
    -r "%ROOT%\agents\rag\requirements.txt" ^
    -r "%ROOT%\agents\codegen\requirements.txt" ^
    -r "%ROOT%\agents\reviewer\requirements.txt" ^
    -r "%ROOT%\agents\db\requirements.txt" ^
    -r "%ROOT%\webapp\backend\requirements.txt" ^
    -r "%ROOT%\target-app\requirements.txt" ^
    -q >nul 2>&1

:: ── Install frontend deps ───────────────────────────────────
echo [2/3] Installing frontend dependencies...
cd /d "%ROOT%\webapp\frontend"
call npm install --silent >nul 2>&1
cd /d "%ROOT%"

:: ── Launch 2 windows ───────────────────────────────────────
echo [3/3] Launching 2 terminal windows...

:: Window 1 — all backend services in one Python process
start "Backend Services" cmd /k "cd /d "%ROOT%" && python scripts/launch_backend.py"
timeout /t 6 /nobreak >nul

:: Window 2 — Vite frontend
start "Frontend :5173" cmd /k "cd /d "%ROOT%\webapp\frontend" && npm run dev"
timeout /t 4 /nobreak >nul

:: ── Print links ─────────────────────────────────────────────
echo.
echo ============================================================
echo  ALL SERVICES STARTED (2 windows)
echo ============================================================
echo.
echo   MAIN UI         http://localhost:5173          ^<-- open this
echo.
echo   Agent Swagger APIs:
echo     Target App    http://localhost:8000/docs
echo     Planner       http://localhost:8010/docs
echo     RAG           http://localhost:8011/docs
echo     DB Query      http://localhost:8012/docs
echo     DB Executor   http://localhost:8013/docs
echo     CodeGen       http://localhost:8014/docs
echo     Reviewer      http://localhost:8015/docs
echo     Webapp        http://localhost:8020/docs
echo.
echo   FIRST-TIME ONLY — ingest docs into RAG:
echo     cd rag-agent ^&^& python ingest.py
echo.
echo ============================================================
echo.

start http://localhost:5173
echo  Browser opening http://localhost:5173...
echo  Close this window whenever you like.
echo.
pause
