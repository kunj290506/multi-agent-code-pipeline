#!/usr/bin/env bash
# Multi-Agent Pipeline — Start All Services (Linux / macOS)
# Run from repo root: bash scripts/start_all.sh
#
# Prerequisites:
#   - Ollama installed and running on the host (http://localhost:11434)
#   - Python 3.11+ with all agent requirements installed
#   - Node.js 18+ (for webapp frontend)
#   - Docker running (for n8n)

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIDS=()

cleanup() {
    echo ""
    echo "Stopping all services..."
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    exit 0
}
trap cleanup SIGINT SIGTERM

echo "Starting n8n (Docker)..."
docker compose --project-directory "$REPO_ROOT" up -d

echo "Starting Target App (port 8000)..."
(cd "$REPO_ROOT/target-app" && python -m uvicorn app:app --host 0.0.0.0 --port 8000) &
PIDS+=($!)
sleep 2

echo "Starting Planner Agent (port 8010)..."
(cd "$REPO_ROOT/planner-agent" && python -m uvicorn api:app --host 0.0.0.0 --port 8010) &
PIDS+=($!)

echo "Starting RAG Agent (port 8011)..."
(cd "$REPO_ROOT/rag-agent" && python -m uvicorn api:app --host 0.0.0.0 --port 8011) &
PIDS+=($!)

echo "Starting DB Query Agent (port 8012)..."
(cd "$REPO_ROOT/db-agent" && python -m uvicorn api:app --host 0.0.0.0 --port 8012) &
PIDS+=($!)

echo "Starting DB Executor Agent (port 8013)..."
(cd "$REPO_ROOT/db-agent" && python -m uvicorn executor_api:app --host 0.0.0.0 --port 8013) &
PIDS+=($!)

echo "Starting CodeGen Agent (port 8014)..."
(cd "$REPO_ROOT/codegen-agent" && python -m uvicorn api:app --host 0.0.0.0 --port 8014) &
PIDS+=($!)

echo "Starting Reviewer Agent (port 8015)..."
(cd "$REPO_ROOT/reviewer-agent" && python -m uvicorn api:app --host 0.0.0.0 --port 8015) &
PIDS+=($!)

sleep 2

echo "Starting Webapp Backend (port 8020)..."
(cd "$REPO_ROOT/webapp/backend" && python -m uvicorn main:app --host 0.0.0.0 --port 8020) &
PIDS+=($!)

echo "Starting Webapp Frontend (port 5173)..."
(cd "$REPO_ROOT/webapp/frontend" && npm run dev) &
PIDS+=($!)

echo ""
echo "All services started. Press Ctrl+C to stop all."
echo ""
echo "Service URLs:"
echo "  Target App:       http://localhost:8000/docs"
echo "  Planner Agent:    http://localhost:8010/docs"
echo "  RAG Agent:        http://localhost:8011/docs"
echo "  DB Query Agent:   http://localhost:8012/docs"
echo "  DB Executor:      http://localhost:8013/docs"
echo "  CodeGen Agent:    http://localhost:8014/docs"
echo "  Reviewer Agent:   http://localhost:8015/docs"
echo "  Webapp Backend:   http://localhost:8020/docs"
echo "  Webapp Frontend:  http://localhost:5173"
echo "  n8n Dashboard:    http://localhost:5678  (admin / changeme)"
echo ""
echo "Run the evaluation: python eval/run_eval.py"

wait
