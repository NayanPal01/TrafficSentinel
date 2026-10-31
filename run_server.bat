@echo off
REM Launch the TrafficSentinel AI FastAPI Server & Web Dashboard on port 8765.
setlocal
cd /d "%~dp0"
if not exist ".venv" (
    echo No .venv found. Run setup.bat first.
    pause
    exit /b 1
)
call .venv\Scripts\activate.bat
echo Starting TrafficSentinel AI DSS Backend & Dashboard on http://localhost:8765 ...
call "%~dp0.venv\Scripts\python.exe" server.py
pause

