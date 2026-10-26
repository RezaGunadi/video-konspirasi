@echo off
rem Klik dua kali: tarik semua video yang sudah jadi dari mini PC ke folder output\ di laptop ini.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tarik-hasil.ps1"
pause
