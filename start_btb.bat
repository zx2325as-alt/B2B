@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion

:: Set Hugging Face Mirror for China
set HF_ENDPOINT=https://hf-mirror.com

echo ===================================================
echo       BtB Deep Dialogue System - One-Click Start
echo ===================================================

cd /d "%~dp0"

echo [1/2] Checking dependencies...
pip install -r requirements.txt > nul 2>&1
if %errorlevel% neq 0 (
    echo [Warning] Dependency installation failed. Please check requirements.txt
) else (
    echo [Success] Dependencies ready
)

echo [2/2] Launching services via Python Launcher...
python launcher.py

pause
