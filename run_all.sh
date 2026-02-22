#!/bin/bash

# Ensure child processes are killed when this script exits
trap 'kill 0' SIGINT SIGTERM EXIT

echo "========================================"
echo "Starting Battle-Agents..."
echo "========================================"

# Navigate to project root
cd "$(dirname "$0")" || exit

# Activate virtual environment if it exists
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
else
    echo "[Warning] .venv not found at project root. Using system python."
fi

# Set PYTHONPATH so absolute imports work correctly
export PYTHONPATH="$(pwd)"

# Battle-Agents serves the frontend directly from the FastAPI backend,
# so we only need to start the Python app.
echo "[Server] Starting FastAPI (Backend API + Static Frontend)..."
python frontend/server/app.py "$@" &

echo "========================================"
echo "Server running at: http://localhost:8000"
echo "Press Ctrl+C to stop."
echo "========================================"

wait
