@echo off
echo ============================================================
echo   STARTING OFFICIAL N8N DOCKER CONTAINER
echo ============================================================
echo.

cd /d "%~dp0"

echo [1/3] Checking Docker Engine status...
docker ps >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo.
    echo [!] Docker Desktop is not running yet.
    echo     Please open "Docker Desktop" from your Windows Start Menu,
    echo     wait for it to show "Engine running", and press any key to continue.
    echo.
    pause
)

echo [2/3] Launching official n8n container via Docker Compose...
docker compose up -d n8n

echo.
echo [3/3] Opening official n8n in your browser...
timeout /t 3 /nobreak >nul
start http://localhost:5678

echo.
echo ============================================================
echo   OFFICIAL N8N RUNNING AT: http://localhost:5678
echo   Username: admin
echo   Password: admin123
echo ============================================================
pause
