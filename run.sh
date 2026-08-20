#!/usr/bin/env bash
# SonicPulse — installs backend deps and starts the API + a static
# server for the frontend. Requires ffmpeg on PATH (see README.md).

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "== SonicPulse setup =="

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "WARNING: ffmpeg not found on PATH. Audio decoding will fail."
  echo "  Install it, e.g. 'sudo apt install ffmpeg' or 'brew install ffmpeg'."
fi

echo "-- Installing backend dependencies --"
cd "$SCRIPT_DIR/backend"
python3 -m venv venv 2>/dev/null || true
# shellcheck disable=SC1091
source venv/bin/activate
pip install --quiet -r requirements.txt

echo "-- Starting FastAPI backend on :8000 --"
uvicorn main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

echo "-- Starting static frontend server on :5500 --"
cd "$SCRIPT_DIR/frontend"
python3 -m http.server 5500 &
FRONTEND_PID=$!

echo ""
echo "SonicPulse is running:"
echo "  Backend : http://localhost:8000  (docs at /docs)"
echo "  Frontend: http://localhost:5500"
echo ""
echo "Press Ctrl+C to stop both servers."

trap 'kill $BACKEND_PID $FRONTEND_PID 2>/dev/null' EXIT
wait
