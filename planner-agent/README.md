# Planner / Orchestrator Agent

## Purpose

The Planner agent is the central orchestrator of the multi-agent code pipeline.
It accepts a plain-language feature request and decomposes it into an ordered
list of subtasks, each assigned to a specific downstream agent.

The planner enforces a strict JSON output schema so that the n8n workflow and
downstream agents can consume the plan deterministically.

---

## Architecture

```
Feature Request (plain text)
        |
        v
  [decompose()]  -->  Ollama (local LLM)
        |
        v
  JSON Plan:
  {
    "feature_request": "...",
    "subtasks": [
      { "task_id": "task_1", "agent": "rag-agent", ... },
      { "task_id": "task_2", "agent": "codegen-agent", ... },
      ...
    ]
  }
```

---

## Project Structure

```
planner-agent/
  config.py          -- Centralized configuration
  planner.py         -- Core decomposition logic and schema validation
  api.py             -- FastAPI HTTP wrapper
  test_planner.py    -- Test script with multiple example inputs
  requirements.txt   -- Python dependencies
  README.md          -- This file
```

---

## Output Schema

Every plan response conforms to this structure:

```json
{
  "feature_request": "Add user authentication with JWT",
  "subtasks": [
    {
      "task_id": "task_1",
      "agent": "rag-agent",
      "description": "Retrieve documentation about the current auth setup.",
      "dependencies": []
    },
    {
      "task_id": "task_2",
      "agent": "db-agent",
      "description": "Generate migration for a sessions table.",
      "dependencies": ["task_1"]
    },
    {
      "task_id": "task_3",
      "agent": "codegen-agent",
      "description": "Implement JWT middleware and login endpoint.",
      "dependencies": ["task_1", "task_2"]
    },
    {
      "task_id": "task_4",
      "agent": "reviewer-agent",
      "description": "Review authentication code for security issues.",
      "dependencies": ["task_3"]
    }
  ]
}
```

### Valid Agent Names

| Agent             | Role                                          |
|-------------------|-----------------------------------------------|
| `rag-agent`       | Documentation retrieval and codebase context   |
| `codegen-agent`   | Code generation (API, UI components)           |
| `reviewer-agent`  | Code review, security, and quality checks      |
| `db-agent`        | Database queries and migration generation      |

---

## Setup

### Prerequisites

- Python 3.10+
- Ollama running locally on port 11434 (for online mode)

### Installation

```bash
cd planner-agent
pip install -r requirements.txt
```

### Configuration

| Variable              | Default                   | Description                    |
|-----------------------|---------------------------|--------------------------------|
| `OLLAMA_BASE_URL`     | `http://localhost:11434`  | Ollama server URL              |
| `OLLAMA_MODEL`        | `mistral`                 | Model for task decomposition   |
| `PLANNER_TEMPERATURE` | `0.1`                     | Sampling temperature           |
| `PLANNER_MAX_TOKENS`  | `2048`                    | Maximum tokens in response     |
| `PLANNER_API_HOST`    | `0.0.0.0`                | API server bind address        |
| `PLANNER_API_PORT`    | `8000`                    | API server port                |

---

## Usage

### Command Line

```bash
# Online mode (requires Ollama)
python planner.py "Add a user authentication system with JWT tokens"

# Offline mode (no Ollama required, deterministic output)
python planner.py --offline "Add a user authentication system with JWT tokens"
```

### HTTP API

```bash
python api.py
# Server starts at http://localhost:8000
```

Endpoints:

- `GET  /health`  -- Health check
- `GET  /schema`  -- Returns the expected JSON schema
- `POST /plan`    -- `{ "feature_request": "...", "offline": false }`

### Running Tests

```bash
python test_planner.py
```

Tests validate:
- Offline decomposition for 5 example feature requests
- JSON extraction from various model output formats (clean JSON, markdown-wrapped, etc.)
- Schema validation catches: missing fields, invalid agents, duplicate IDs, bad dependencies
- Full Ollama integration (skipped if server unavailable)

---

## Integration

The Planner agent is typically the first agent called in the pipeline. The n8n
workflow sends a feature request to `POST /plan`, receives the ordered subtask
list, and then dispatches each subtask to the appropriate downstream agent.
