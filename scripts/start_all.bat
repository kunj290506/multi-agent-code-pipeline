@echo off
setlocal enabledelayedexpansion

:: ============================================================
::  Multi-Agent Pipeline — One-command demo launcher
::  Starts all backend agents and the Vite frontend, waits for
::  every health endpoint, then opens the UI.
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

:: ── Verify dependencies already installed ──────────────────
if not exist "%ROOT%\webapp\frontend\node_modules" (
    echo ERROR: Frontend dependencies are missing.
    echo Run: cd /d "%ROOT%\webapp\frontend" ^&^& npm install
    pause & exit /b 1
)

:: ── Clear stale listeners so old workers cannot conflict ────
echo [1/3] Clearing stale project listeners...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ports=8000,8010,8011,8012,8013,8014,8015,8020,5173; foreach($port in $ports){ Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue } }"

:: ── Launch backend and frontend windows ────────────────────
echo [2/3] Launching backend and frontend...

:: Window 1 — all backend services in one Python process
start "Backend Services" cmd /k "cd /d "%ROOT%" && python scripts/launch_backend.py"
timeout /t 6 /nobreak >nul

:: Window 2 — Vite frontend
start "Frontend :5173" cmd /k "cd /d "%ROOT%\webapp\frontend" && npm run dev"

:: ── Wait for every health endpoint ──────────────────────────
echo [3/3] Waiting for all services (RAG may take a minute)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$urls='http://localhost:5173/','http://localhost:8000/health','http://localhost:8010/health','http://localhost:8011/health','http://localhost:8012/health','http://localhost:8013/health','http://localhost:8014/health','http://localhost:8015/health','http://localhost:8020/health'; $deadline=(Get-Date).AddMinutes(5); do { $ok=$true; foreach($url in $urls){ try { Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3 | Out-Null } catch { $ok=$false; break } }; if($ok){ exit 0 }; Start-Sleep -Seconds 3 } while((Get-Date) -lt $deadline); Write-Host 'ERROR: One or more services did not become healthy.'; exit 1"
if errorlevel 1 (
    echo Startup failed. Check the Backend Services and Frontend :5173 windows.
    pause & exit /b 1
)

:: ── Print links ─────────────────────────────────────────────
echo.
echo ============================================================
echo  ALL SERVICES HEALTHY
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
