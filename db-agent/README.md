# DB Agent -- Query Generation

## Purpose

The DB Agent (query-generation component) converts natural-language requests
into safe, parameterized SQL queries. This module handles **only query
generation** -- query execution, sandboxing, and result handling are built
as a separate component and are out of scope for this module.

---

## Scope and Boundaries

| In Scope                                      | Out of Scope                          |
|-----------------------------------------------|---------------------------------------|
| Natural-language to SQL translation            | Query execution against a live DB     |
| Parameterized query generation                 | Connection pooling and management     |
| Safety validation (block DROP, TRUNCATE, etc.) | Result formatting and pagination      |
| Schema-aware query construction                | ORM integration                       |
| Offline mode for testing                       | Transaction management                |
| HTTP API for inter-agent communication         | Database sandboxing                   |

This separation ensures that the query-generation logic can be developed,
tested, and deployed independently of the execution layer.

---

## Architecture

```
Natural-language request
        |
        v
  [generate_query()]  -->  Ollama (local LLM)
        |
        v
  [_extract_json()]   -- Parse structured response
        |
        v
  [validate_query()]  -- Safety checks (block DROP, unscoped DELETE, etc.)
        |
        v
  JSON response:
  {
    "query": "SELECT ... WHERE ... = ?",
    "parameters": [...],
    "query_type": "SELECT",
    "explanation": "...",
    "safety_check": { "passed": true, "violations": [] }
  }
```

---

## Project Structure

```
db-agent/
  config.py              -- Configuration (Ollama URL, schema, API settings)
  query_generator.py     -- Core NL-to-SQL logic and safety validation
  api.py                 -- FastAPI HTTP wrapper
  test_db_agent.py       -- Test script with safety and generation tests
  requirements.txt       -- Python dependencies
  README.md              -- This file
```

---

## Safety Rules

The following operations are **always blocked**:

- `DROP TABLE`, `DROP DATABASE`, `DROP INDEX`, `DROP VIEW`
- `TRUNCATE`
- `ALTER TABLE`
- `GRANT`, `REVOKE`
- `EXEC`, `EXECUTE`, `xp_*`, `sp_*` (stored procedure calls)

The following patterns are **flagged as unsafe**:

- `DELETE FROM table;` without a `WHERE` clause
- `UPDATE table SET ...;` without a `WHERE` clause
- Statement chaining via semicolons (e.g., `SELECT ...; DROP TABLE ...`)
- SQL comment injection (`--`, `/* */`)

---

## Setup

### Prerequisites

- Python 3.10+
- Ollama running locally on port 11434 (for online mode)

### Installation

```bash
cd db-agent
pip install -r requirements.txt
```

### Configuration

| Variable              | Default                   | Description                     |
|-----------------------|---------------------------|---------------------------------|
| `OLLAMA_BASE_URL`     | `http://localhost:11434`  | Ollama server URL               |
| `OLLAMA_MODEL`        | `mistral`                 | Model for query generation      |
| `DB_AGENT_TEMPERATURE`| `0.1`                     | Sampling temperature            |
| `DB_AGENT_MAX_TOKENS` | `1024`                    | Maximum tokens in response      |
| `DB_AGENT_HOST`       | `0.0.0.0`                | API server bind address         |
| `DB_AGENT_PORT`       | `8002`                    | API server port                 |

---

## Usage

### Command Line

```bash
# Online mode (requires Ollama)
python query_generator.py "Show all tasks assigned to Alice"

# Offline mode (no Ollama required)
python query_generator.py --offline "List all users in the system"
```

### HTTP API

```bash
python api.py
# Server starts at http://localhost:8002
```

Endpoints:

- `GET  /health`    -- Health check
- `GET  /schema`    -- Returns the current database schema
- `POST /generate`  -- `{ "request": "...", "offline": false }`
- `POST /validate`  -- `{ "query": "SELECT ..." }`

### Running Tests

```bash
python test_db_agent.py
```

Tests validate:
- Offline query generation for 4 NL request types
- Safety validation against 11 test queries (safe and unsafe)
- JSON extraction from various formats
- Response structure validation
- Full Ollama integration (skipped if server unavailable)

---

## Database Schema

The default placeholder schema used for query generation:

```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE,
    role TEXT DEFAULT 'member',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    status TEXT DEFAULT 'pending',
    assigned_to INTEGER,
    priority TEXT DEFAULT 'medium',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (assigned_to) REFERENCES users(id)
);

CREATE TABLE comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_id) REFERENCES tasks(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);
```

---

## Integration with Execution Layer

The execution layer (built separately) should:
1. Call `POST /generate` with a natural-language request.
2. Receive the parameterized query and parameters.
3. Execute the query in a sandboxed database connection.
4. Return formatted results.

The query-generation module guarantees that all returned queries have passed
safety validation. The execution layer should still enforce additional
protections (read-only connections, timeouts, row limits, etc.).
