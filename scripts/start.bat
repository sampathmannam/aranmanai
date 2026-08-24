@echo off
REM Aranmanai start script. Runs API + frontend in two windows.
REM Requires: venv at .\venv, dependencies installed (pip install -r requirements.txt),
REM model downloaded (python scripts\download_model.py --model qwen-1.5b)
REM or ARANMANAI_LLM_BACKEND=mock for development without a real model.

setlocal
cd /d "%~dp0\.."

REM Initialize DB on first run
if not exist "data\aranmanai.db" (
  echo [1/3] First run: initializing database...
  call venv\Scripts\python.exe scripts\init_db.py
)

REM Start API in background
echo [2/3] Starting API on http://127.0.0.1:8080 ...
start "Aranmanai-API" /MIN call venv\Scripts\python.exe -m uvicorn aranmanai.api.main:app --host 127.0.0.1 --port 8080

REM Give API a moment to start
timeout /t 3 /nobreak >nul

REM Start frontend
echo [3/3] Starting frontend on http://127.0.0.1:8501 ...
start "Aranmanai-UI" /MIN call venv\Scripts\python.exe -m streamlit run src\aranmanai\frontend\app.py --server.port 8501

echo.
echo Aranmanai running:
echo   API:       http://127.0.0.1:8080
echo   Frontend:  http://127.0.0.1:8501
echo   API docs:  http://127.0.0.1:8080/docs
echo.
echo Default login: admin / Aranmanai!Dev!2026
echo.
echo Close this window and the two Aranmanai-* windows to stop.
pause
