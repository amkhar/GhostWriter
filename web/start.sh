#!/bin/bash
# Start GhostWriter frontend (backend must be started separately)
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Starting GhostWriter frontend on :3000"
echo "  (Start backend separately: .venv/bin/uvicorn web.api.server:app --port 8000 --reload)"
echo ""

cd "$DIR/frontend"
if [ ! -d "node_modules" ]; then
  npm install
fi
npm run dev
