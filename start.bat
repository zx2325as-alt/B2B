@echo off
chcp 65001 >nul
echo ===================================================
echo Starting BtB project
echo ===================================================

set "BASE_DIR=%~dp0"

echo [0/3] Cleaning old dev processes on ports 5174 / 8001 / 7474 / 7687...
powershell -NoProfile -Command "$ports = 5174,8001,7474,7687; foreach ($port in $ports) { Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue } }"

REM Start graph store (Neo4j)
echo [1/3] Starting Neo4j graph store on ports 7474 / 7687...
where java >nul 2>nul
if %errorlevel%==0 (
  start "BtB Neo4j" cmd /k "cd /d "%BASE_DIR%backend\app\models\neo4j-community-5.18.1" && bin\neo4j.bat console"
) else (
  echo Java was not found. Skipping Neo4j; install Java 17+ or set JAVA_HOME to enable graph storage.
)

REM Start backend (FastAPI)
echo [2/3] Starting backend on port 8001...
start "BtB Backend" cmd /k "cd /d "%BASE_DIR%backend" &&  python -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload"

REM Start frontend (Vue + Vite)
echo [3/3] Starting frontend on port 5174...
start "BtB Frontend" cmd /k "cd /d "%BASE_DIR%frontend" && npm run dev"

echo ===================================================
echo Backend API docs: http://localhost:8001/docs
echo Frontend App:     http://localhost:5174
echo Neo4j Browser:    http://localhost:7474
echo ===================================================
pause



