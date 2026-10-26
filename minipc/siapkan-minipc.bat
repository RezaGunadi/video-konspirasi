@echo off
rem Klik kanan file ini -> Run as administrator (di mini PC).
net session >nul 2>&1
if %errorlevel% neq 0 (
  echo Jalankan dengan klik kanan -^> Run as administrator.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0siapkan-minipc.ps1"
pause
