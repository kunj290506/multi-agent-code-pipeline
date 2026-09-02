# Code-Gen Agent

## Purpose

The Code-Gen Agent generates a single code artifact at a time from a
structured specification. It uses the local Ollama model for LLM-powered
generation and also provides an offline (deterministic, template-based)
mode for testing.

Supported artifact types:
- **REST endpoints** (Python/FastAPI, Node/Express)
- **React components** (JavaScript/JSX)
- **Utility modules** (Python)
- **Database migrations** (SQLite)

---

## Input Specification Format

The agent accepts a strict JSON specification with the following fields:

| Field           | Type       | Required | Description                                    |
|-----------------|------------|----------|------------------------------------------------|
| `artifact_type` | string     | Yes      | One of: `rest_endpoint`, `react_component`, `utility_module`, `database_migration` |
| `name`          | string     | Yes      | PascalCase name for the artifact               |
| `description`   | string     | Yes      | What the artifact should do                    |
| `language`      | string     | No       | Target language (default: `python`)            |
| `framework`     | string     | No       | Target framework (default: `fastapi`)          |
| `dependencies`  | string[]   | No       | Required packages                              |
| `constraints`   | string[]   | No       | Additional requirements                        |
| `context`       | string     | No       | Related schema or code for reference           |

### Example Input

```json
{
  "artifact_type": "rest_endpoint",
  "name": "UserProfile",
  "description": "An endpoint that returns user profile details by user ID.",
  "language": "python",
  "framework": "fastapi",
  "dependencies": ["fastapi", "pydantic"],
  "constraints": ["must include input validation", "return 404 if user not found"]
}
```

---

## Output Format

The agent returns a JSON object with the generated code and metadata:

| Field           | Type       | Description                                    |
|-----------------|------------|------------------------------------------------|
| `artifact_type` | string     | Echoed from input                              |
| `name`          | string     | Echoed from input                              |
| `language`      | string     | Language of the generated code                 |
| `framework`     | string     | Framework used                                 |
| `code`          | string     | The generated source code                      |
| `filename`      | string     | Suggested filename                             |
| `dependencies`  | string[]   | Required packages                              |
| `explanation`   | string     | Brief description of the generated code        |
| `warnings`      | string[]   | Any caveats or warnings                        |

---

## Project Structure

```
codegen-agent/
  config.py           -- Configuration (Ollama URL, model, API settings)
  spec_schema.py       -- Input spec and output schema (Pydantic models)
  generator.py         -- Core generation logic (online + offline)
  api.py               -- FastAPI HTTP wrapper
  test_codegen.py      -- Test script
  requirements.txt     -- Python dependencies
  README.md            -- This file
```

---

## Setup

### Prerequisites

- Python 3.10+
- Ollama running locally on port 11434 (for online mode only)

### Installation

```bash
cd codegen-agent
pip install -r requirements.txt
```

### Running the API Server

```bash
python api.py
# Server starts at http://localhost:8014
```

---

## Usage

### HTTP API

| Method | Endpoint       | Description                              |
|--------|----------------|------------------------------------------|
| `GET`  | `/health`      | Health check                             |
| `GET`  | `/spec-schema` | Returns input and output JSON Schemas    |
| `POST` | `/generate`    | Generate a code artifact                 |

#### POST /generate

Request body:
```json
{
  "spec": {
    "artifact_type": "rest_endpoint",
    "name": "UserProfile",
    "description": "Returns user profile by ID.",
    "language": "python",
    "framework": "fastapi"
  },
  "offline": false
}
```

Set `"offline": true` to use template-based generation without Ollama.

### Command Line (via generator.py)

```python
from generator import generate_artifact_offline
from spec_schema import ArtifactSpec

spec = ArtifactSpec(
    artifact_type="rest_endpoint",
    name="UserProfile",
    description="Returns user profile by ID.",
)
artifact = generate_artifact_offline(spec)
print(artifact.code)
```

### Running Tests

```bash
python test_codegen.py
```

Tests cover:
- Offline generation for all 4 artifact types
- Output format validation and JSON round-trip
- Helper functions (snake_case, filename suggestion)
- JSON extraction from various model output formats
- API endpoint functionality
- Online generation (skipped if Ollama is not running)

---

## Configuration

| Variable            | Default                   | Description                    |
|---------------------|---------------------------|--------------------------------|
| `OLLAMA_BASE_URL`   | `http://localhost:11434`  | Ollama server URL              |
| `OLLAMA_MODEL`      | `qwen2.5:7b-instruct-q4_K_M` | Model for code generation |
| `CODEGEN_TEMPERATURE` | `0.2`                   | Sampling temperature           |
| `CODEGEN_MAX_TOKENS`  | `2048`                  | Maximum tokens in response     |
| `CODEGEN_HOST`      | `0.0.0.0`                | API server bind address        |
| `CODEGEN_PORT`      | `8014`                    | API server port                |
