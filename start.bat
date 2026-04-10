@echo off
chcp 65001 >nul
echo ===================================================
echo Starting BtB project
echo ===================================================

set "BASE_DIR=%~dp0"

echo [0/2] Cleaning old dev processes on ports 5173 / 8001...
powershell -NoProfile -Command "$ports = 5173,8001; foreach ($port in $ports) { Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue } }"

REM Start backend (FastAPI)
echo [1/2] Starting backend on port 8001...
start "BtB Backend" cmd /k "cd /d "%BASE_DIR%backend" &&  python -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload"

REM Start frontend (Vue + Vite)
echo [2/2] Starting frontend on port 5173...
start "BtB Frontend" cmd /k "cd /d "%BASE_DIR%frontend" && npm run dev"

echo ===================================================
echo Backend API docs: http://localhost:8001/docs
echo Frontend App:     http://localhost:5173
echo ===================================================
pause




