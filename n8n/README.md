# n8n Orchestration Workflow

## Purpose

This directory contains the n8n workflow definition that orchestrates the
multi-agent code pipeline. The workflow connects all agents through a visual,
event-driven pipeline triggered by an incoming webhook.

---

## Workflow Overview

```
Webhook (POST /feature-request)
        |
        v
  Call Planner Agent (POST /plan)
        |
        v
  Parse Plan Response
        |
        v
  Split Subtasks (one item per subtask)
        |
        v
  Route to Agent (Switch by agent name)
        |
   +-----------+-----------+-----------+
   |           |           |           |
   v           v           v           v
RAG Agent   CodeGen     Reviewer    DB Agent
(port 8001) (port 8003) (port 8004) (port 8002)
   |           |           |           |
   +-----------+-----------+-----------+
        |
        v
  Aggregate Results
        |
        v
  Log Pipeline Results
        |
        v
  Webhook Response
```

---

## Workflow Nodes

| Node                          | Type         | Description                                       |
|-------------------------------|--------------|---------------------------------------------------|
| Webhook Trigger               | Webhook      | Receives POST requests at `/feature-request`      |
| Call Planner Agent            | HTTP Request | Calls planner at `http://host.docker.internal:8000/plan` |
| Parse Plan Response           | Code         | Extracts subtasks from the planner response       |
| Split Subtasks                | Code         | Creates one workflow item per subtask              |
| Route to Agent                | Switch       | Routes each subtask to the correct agent by name  |
| Call RAG Agent                | HTTP Request | `POST http://host.docker.internal:8001/query`     |
| Call CodeGen Agent (Placeholder)| HTTP Request | `POST http://host.docker.internal:8003/generate` |
| Call Reviewer Agent (Placeholder)| HTTP Request | `POST http://host.docker.internal:8004/review` |
| Call DB Agent                 | HTTP Request | `POST http://host.docker.internal:8002/generate`  |
| Aggregate Results             | Code         | Collects all agent responses                       |
| Log Pipeline Results          | Code         | Creates a pipeline run log entry                   |

---

## Agent Port Mapping

| Agent            | Port | Status      |
|------------------|------|-------------|
| Planner Agent    | 8000 | Implemented |
| RAG Agent        | 8001 | Implemented |
| DB Agent         | 8002 | Implemented |
| CodeGen Agent    | 8003 | Placeholder |
| Reviewer Agent   | 8004 | Placeholder |

---

## Setup

### Prerequisites

- Docker and Docker Compose installed
- All agent services running locally (or adjust URLs in the workflow)

### 1. Start the n8n Container

```bash
# From the project root
docker compose up -d n8n
```

### 2. Access the n8n Dashboard

- URL: http://localhost:5678
- Username: `admin`
- Password: `changeme`

### 3. Import the Workflow

1. Open the n8n dashboard in your browser.
2. Click the **three-dot menu** (top right) and select **Import from File**.
3. Select `n8n/workflow.json` from this directory.
4. The workflow will appear in your workflow list.

Alternatively, use the n8n CLI or API:

```bash
# Via the n8n API
curl -X POST http://localhost:5678/api/v1/workflows \
  -H "Content-Type: application/json" \
  -u admin:changeme \
  -d @n8n/workflow.json
```

### 4. Activate the Workflow

1. Open the imported workflow.
2. Toggle the **Active** switch in the top right corner.
3. The webhook endpoint is now live.

### 5. Start the Agent Services

```bash
# Terminal 1: Planner Agent
cd planner-agent && python api.py

# Terminal 2: RAG Agent
cd rag-agent && python api.py

# Terminal 3: DB Agent
cd db-agent && python api.py
```

---

## Testing the Workflow

### Send a Test Request

```bash
curl -X POST http://localhost:5678/webhook/feature-request \
  -H "Content-Type: application/json" \
  -d '{
    "feature_request": "Add a user authentication system with JWT tokens",
    "offline": true
  }'
```

### Expected Response

The webhook returns a JSON response containing:
- Pipeline status
- Log of each step's input and output
- Aggregated results from all agents

### Offline Mode

Set `"offline": true` in the request body to use offline/deterministic mode
for the planner agent. This is useful for testing the workflow without
a running Ollama server.

---

## Logging

Each pipeline run generates a log entry with:
- `pipeline_run_id`: Unique identifier for the run
- `completed_at`: ISO timestamp of completion
- `steps`: Array of step results with timestamps

In the current implementation, logs are returned in the webhook response.
For production use, the "Log Pipeline Results" node can be extended to
write to a local SQLite database or log file.

---

## Networking

The workflow uses `host.docker.internal` to reach agent services running
on the host machine from inside the n8n Docker container.

- On **Docker Desktop** (Windows/macOS): `host.docker.internal` is
  available by default.
- On **Linux**: You may need to add `--add-host=host.docker.internal:host-gateway`
  to the Docker run command, or add it to the `docker-compose.yml`:

```yaml
n8n:
  extra_hosts:
    - "host.docker.internal:host-gateway"
```
