@echo off
title Video Konspirasi AI
cd /d "%~dp0"
rem Kalau server sudah jalan, cukup buka browser.
powershell -NoProfile -Command "try { Invoke-WebRequest http://127.0.0.1:3220/api/status -UseBasicParsing -TimeoutSec 5 | Out-Null; exit 0 } catch { exit 1 }"
if %errorlevel%==0 (
  start "" http://localhost:3220
  exit /b
)
start "" /min cmd /c "timeout /t 3 /nobreak >nul & start http://localhost:3220"
".venv\Scripts\python.exe" app.py
pause
