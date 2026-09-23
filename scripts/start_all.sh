#!/usr/bin/env bash
# Multi-Agent Pipeline — Start All Services (Linux / macOS)
# Run from repo root: bash scripts/start_all.sh
#
# Window 1 (this terminal): all Python backend agents via launch_backend.py
# Window 2: Vite frontend (opened in background)
#
# Prerequisites:
#   - Python 3.11+ with all agent requirements installed
#   - Node.js 18+ (for webapp frontend)
#   - Ollama running on the host (http://localhost:11434)  [optional for offline mode]

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Export local configuration before any Python service is started.
if [ -f "$REPO_ROOT/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    . "$REPO_ROOT/.env"
    set +a
fi

: "${LLM_PROVIDER:=groq}"
: "${GROQ_MODEL:=qwen/qwen3.8-27b}"
export LLM_PROVIDER GROQ_MODEL

if [ "$LLM_PROVIDER" = "groq" ] && [ -z "${GROQ_API_KEY:-}" ]; then
    echo "ERROR: GROQ_API_KEY is not set. Add it to .env or export it before starting."
    exit 1
fi

echo ""
echo "============================================================"
echo "  MULTI-AGENT PIPELINE STARTUP"
echo "============================================================"

#  Install Python deps (fast / silent on repeat runs) 
echo "[1/3] Installing Python dependencies..."
python -m pip install \
    -r "$REPO_ROOT/agents/planner/requirements.txt" \
    -r "$REPO_ROOT/agents/rag/requirements.txt" \
    -r "$REPO_ROOT/agents/codegen/requirements.txt" \
    -r "$REPO_ROOT/agents/reviewer/requirements.txt" \
    -r "$REPO_ROOT/agents/db/requirements.txt" \
    -r "$REPO_ROOT/webapp/backend/requirements.txt" \
    -q

#  Install frontend deps 
echo "[2/3] Installing frontend dependencies..."
(cd "$REPO_ROOT/webapp/frontend" && npm install --silent)

#  Launch frontend in background 
echo "[3/3] Starting frontend in background (port 5173)..."
(cd "$REPO_ROOT/webapp/frontend" && npm run dev) &
FRONTEND_PID=$!

echo ""
echo "============================================================"
echo "  Starting all backend services in this window..."
echo "============================================================"
echo ""
echo "  Frontend:       http://localhost:5173  (pid $FRONTEND_PID)"
echo "  Webapp Backend: http://localhost:8020/docs"
echo ""
echo "  Press Ctrl+C to stop everything."
echo "============================================================"
echo ""

#  Run all backend agents in this window (single process, labelled logs) 
cleanup() {
    kill "$FRONTEND_PID" 2>/dev/null || true
    wait "$FRONTEND_PID" 2>/dev/null || true
}
trap cleanup SIGINT SIGTERM EXIT
python "$REPO_ROOT/scripts/launch_backend.py"
