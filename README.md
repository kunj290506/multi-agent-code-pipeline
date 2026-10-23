# Multi-Agent Code Pipeline

A local multi-agent code pipeline studio with stage orchestration, code studio, live diffs, and security approvals.

## Prerequisites
- Python 3.10+
- Node.js 18+
- Ollama (`http://localhost:11434`) with `qwen2.5:7b-instruct-q4_K_M`
- Optional: Docker Desktop (for n8n at `:5678`)

## Environment Setup
Copy the template and adjust if needed:
```bash
cp .env.example .env
```
Default config runs entirely on `localhost` with zero cloud calls.

## Start All Services
Start the entire stack (Ollama check, backend, frontend, and browser launch):
```bash
# Windows
start.bat

# Linux / macOS / Cross-platform
python start.py
```
To stop everything cleanly:
```bash
stop.bat  # or python stop.py
```

## Service Links
| Service | URL |
|---|---|
| Frontend UI | http://localhost:5173 |
| Backend API Docs | http://localhost:8000/docs |
| Backend Health | http://localhost:8000/health |
| n8n Editor | http://localhost:5678 |

## Adding a Tool
1. In `backend/tools.py`, add schema to `TOOL_DEFINITIONS`.
2. Implement your tool function `tool_your_name(...)`.
3. Dispatch it in `backend/agent.py` inside `run_agent_loop()`.

## Adding an n8n Workflow
1. Place your workflow JSON file in `n8n/my-workflow.json`.
2. Add name to `ALLOWED_WORKFLOWS` in `backend/n8n_client.py`.
3. The backend imports and exposes it to `trigger_workflow`.

## Notes & Design Decisions
- If Docker/n8n is offline, workflows fall back gracefully with clear notices.
- Clean lightweight code viewer used instead of heavy Monaco bundle.
- Sandboxed commands block chaining (&&, ;) to guarantee isolation.
