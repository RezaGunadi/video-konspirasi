@echo off
cd /d "d:\smart ai\video-konspirasi"
start "" ".venv\Scripts\python.exe" uploader_gui.py
timeout /t 2 /nobreak >nul
start "" http://127.0.0.1:3301
