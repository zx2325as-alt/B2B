@echo off
chcp 65001 >nul
echo ===================================================
echo Starting BtB project
echo ===================================================

set "BASE_DIR=%~dp0"

REM Start backend (FastAPI)
echo [1/2] Starting backend on port 8000...
start "BtB Backend" cmd /k "cd /d "%BASE_DIR%backend" && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"

REM Start frontend (Vue + Vite)
echo [2/2] Starting frontend on port 5173...
start "BtB Frontend" cmd /k "cd /d "%BASE_DIR%frontend" && npm run dev"

echo ===================================================
echo Backend API docs: http://localhost:8000/docs
echo Frontend App:     http://localhost:5173
echo ===================================================
pause