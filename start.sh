#!/bin/bash
# Launch Secure Document Room — backend + frontend

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Starting Secure Document Room..."
echo ""
echo "Backend: http://localhost:8000"
echo "Frontend: http://localhost:3000"
echo ""
echo "Press Ctrl+C to stop both servers."
echo ""

# Backend
cd "$ROOT/backend"
if [ ! -f .env ]; then
  cp .env.example .env
  echo "[!] Created .env from .env.example — set ANTHROPIC_API_KEY in backend/.env"
fi

uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

# Frontend
cd "$ROOT/frontend"
npm run dev &
FRONTEND_PID=$!

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; echo 'Stopped.'" EXIT INT TERM
wait
