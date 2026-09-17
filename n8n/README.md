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
(port 8011) (port 8014) (port 8015) (port 8012)
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

The CodeGen path expands into a full retry branch described in the
[CodeGen → Reviewer Retry Branch](#codegen--reviewer-retry-branch) section below.

---

## Workflow Nodes

| Node                          | Type         | Description                                                             |
|-------------------------------|--------------|-------------------------------------------------------------------------|
| Webhook Trigger               | Webhook      | Receives POST requests at `/feature-request`                           |
| Call Planner Agent            | HTTP Request | Calls planner at `http://host.docker.internal:8010/plan`               |
| Parse Plan Response           | Code         | Extracts subtasks from the planner response                            |
| Split Subtasks                | Code         | Creates one workflow item per subtask                                   |
| Route to Agent                | Switch       | Routes each subtask to the correct agent by name                       |
| Call RAG Agent                | HTTP Request | `POST http://host.docker.internal:8011/query`                          |
| Call CodeGen Agent            | HTTP Request | `POST http://host.docker.internal:8014/generate` (first attempt)       |
| Call Reviewer Post-CodeGen    | HTTP Request | `POST http://host.docker.internal:8015/review` (first-attempt review)  |
| Check Verdict                 | Switch       | Routes on `verdict`: output 0 = pass, output 1 = fail                  |
| Retry CodeGen with Issues     | HTTP Request | `POST http://host.docker.internal:8014/generate` with `prior_issues`   |
| Post-Retry Reviewer           | HTTP Request | `POST http://host.docker.internal:8015/review` (second-attempt review) |
| Merge CodeGen Results         | Merge        | Combines the pass path and the retry path before aggregation           |
| Call Reviewer Agent           | HTTP Request | Standalone reviewer for subtasks routed directly to `reviewer-agent`   |
| Call DB Agent                 | HTTP Request | `POST http://host.docker.internal:8012/generate`                       |
| Aggregate Results             | Code         | Collects all agent responses                                           |
| Log Pipeline Results          | Code         | Creates a pipeline run log entry                                        |

---

## Agent Port Mapping

| Agent             | Port | Status      |
|-------------------|------|-------------|
| Planner Agent     | 8010 | Implemented |
| RAG Agent         | 8011 | Implemented |
| DB Agent (query)  | 8012 | Implemented |
| DB Agent (exec)   | 8013 | Implemented |
| CodeGen Agent     | 8014 | Implemented |
| Reviewer Agent    | 8015 | Implemented |

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

## CodeGen → Reviewer Retry Branch

When a `codegen-agent` subtask is executed in n8n, the workflow runs a two-attempt
retry loop before handing results to the aggregation step:

```
Call CodeGen Agent (first attempt)
        |
        v
Call Reviewer Post-CodeGen
        |
        v
  Check Verdict (Switch)
     |          |
   pass        fail
     |          |
     v          v
     |    Retry CodeGen with Issues
     |    (prior_issues forwarded in body)
     |          |
     |          v
     |    Post-Retry Reviewer
     |          |
     +-----------+
           |
           v
   Merge CodeGen Results
           |
           v
   Aggregate Results
```

### What triggers a retry

The **Check Verdict** Switch node evaluates `$json.verdict` from the first reviewer
response. A `"fail"` verdict routes execution to the retry path; a `"pass"` verdict
skips straight to the Merge node.

### What data is forwarded on retry

The **Retry CodeGen with Issues** node sends the full `issues` array from the first
review to the code-gen agent as `prior_issues`. This gives the LLM complete context
about every reported problem so it can address them all in a single regeneration
attempt.

### How the Merge node collects both paths

**Merge CodeGen Results** (mode: `combine`, `mergeByPosition`) has two inputs:

- **Input 0** — receives the first-attempt reviewer result directly from Check Verdict
  output 0 (the pass path).
- **Input 1** — receives the post-retry reviewer result from Post-Retry Reviewer.

Because n8n's merge-by-position mode waits for both inputs before emitting,
whichever path was taken determines which input carries data. The node then
passes the combined item to Aggregate Results.

### Writing the file after retry

Post-retry code is always written to `target-app/` regardless of the second
reviewer verdict. This matches the `"exhausted"` verdict behaviour in the Python
orchestrator: after the retry budget is consumed the code is persisted so the
user can inspect it even if it did not achieve a clean pass.

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
