#!/bin/bash
# Start both GhostWriter backend and frontend
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$DIR/.." && pwd)"
VENV="$PROJECT_ROOT/.venv/bin"

echo "👻 Starting GhostWriter Web UI..."
echo ""

# Backend
echo "→ Starting API server on :8000"
cd "$PROJECT_ROOT"
"$VENV/uvicorn" web.api.server:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

# Frontend
echo "→ Starting frontend on :3000"
cd "$DIR/frontend"
if [ ! -d "node_modules" ]; then
  echo "  Installing frontend dependencies..."
  npm install
fi
npm run dev &
FRONTEND_PID=$!

echo ""
echo "✅ GhostWriter running:"
echo "   Frontend: http://localhost:3000"
echo "   API:      http://localhost:8000"
echo ""
echo "Press Ctrl+C to stop."

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM
wait
