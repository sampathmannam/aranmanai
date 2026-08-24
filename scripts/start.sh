#!/usr/bin/env bash
# Aranmanai start script (Linux/macOS).
# Same workflow as start.bat: init DB, start API, start frontend.

set -e
cd "$(dirname "$0")/.."

# Initialize DB on first run
if [ ! -f "data/aranmanai.db" ]; then
  echo "[1/3] First run: initializing database..."
  ./venv/bin/python scripts/init_db.py
fi

# Start API in background
echo "[2/3] Starting API on http://127.0.0.1:8080 ..."
./venv/bin/python -m uvicorn aranmanai.api.main:app --host 127.0.0.1 --port 8080 &
API_PID=$!

sleep 3

# Start frontend
echo "[3/3] Starting frontend on http://127.0.0.1:8501 ..."
./venv/bin/python -m streamlit run src/aranmanai/frontend/app.py --server.port 8501 &
FE_PID=$!

echo
echo "Aranmanai running:"
echo "  API:       http://127.0.0.1:8080"
echo "  Frontend:  http://127.0.0.1:8501"
echo "  API docs:  http://127.0.0.1:8080/docs"
echo
echo "Default login: admin / Aranmanai!Dev!2026"
echo
echo "Press Ctrl+C to stop (API PID=$API_PID, Frontend PID=$FE_PID)"
wait
