@echo off
cd /d "%~dp0"

rem Always kill whatever is listening on port 5000 BEFORE starting a new process.
rem Otherwise a re-run after code changes silently opens a tab on the stale old process
rem (same script that stop.bat uses, see scripts\stop.ps1) and already-fixed bugs keep
rem looking "alive" because the running code was never actually replaced.
echo Stopping any process on port 5000...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop.ps1"

rem Give Windows a moment to actually free the port after taskkill before rebinding.
timeout /t 2 /nobreak >nul

where python >nul 2>nul
if errorlevel 1 (
    echo Python not found. Install Python 3.10+ from python.org and try again.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo First run: creating isolated environment...
    python -m venv .venv
    ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
    echo Installing dependencies...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)

echo Starting Рятувальничок...
start "" ".venv\Scripts\pythonw.exe" run.py

rem Poll until the server actually responds (up to ~20s) instead of a fixed sleep.
set /a tries=0
:waitloop
curl -s -o nul -m 1 http://127.0.0.1:5000/
if not errorlevel 1 goto ready
set /a tries+=1
if %tries% geq 40 goto ready
timeout /t 1 /nobreak >nul
goto waitloop

:ready
start "" http://127.0.0.1:5000
exit
