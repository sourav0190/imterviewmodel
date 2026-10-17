@echo off
echo Starting AI Proctoring Backend Service...
cd /d "%~dp0"
call .venv\Scripts\python.exe main.py
pause
