@echo off
cd /d "%~dp0"
call venv\Scripts\activate.bat
uvicorn main:app --reload --port 8081
pause
