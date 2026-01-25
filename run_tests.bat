
@echo off
setlocal
cd /d "%~dp0"

echo ==========================================
echo      B2B Automated Test Suite
echo ==========================================
echo.
echo [1/3] Preparing Environment...
set PYTHONPATH=%CD%

echo [2/3] Running Tests...
echo Output will be saved to test_report.txt
echo.

(
    echo ==========================================
    echo Test Report - %DATE% %TIME%
    echo ==========================================
    echo.
    python -m unittest discover -s tests -p "test_*.py" -v
) > test_report.txt 2>&1

echo [3/3] Tests Completed.
echo.
echo ==========================================
echo           Test Report Summary
echo ==========================================
type test_report.txt
echo.
echo ==========================================
echo Report saved to: %CD%\test_report.txt
echo.
pause
