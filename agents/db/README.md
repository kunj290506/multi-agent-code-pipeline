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
| `OLLAMA_MODEL`        | `qwen2.5:7b-instruct-q4_K_M` | Model for query generation      |
| `DB_AGENT_TEMPERATURE`| `0.1`                     | Sampling temperature            |
| `DB_AGENT_MAX_TOKENS` | `1024`                    | Maximum tokens in response      |
| `DB_AGENT_HOST`       | `0.0.0.0`                | API server bind address         |
| `DB_AGENT_PORT`       | `8012`                    | API server port                 |

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
# Server starts at http://localhost:8012
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

The schema mirrors `target-app/app.py` `SCHEMA_SQL` exactly. Update both locations if the target-app schema changes.

| Table      | Columns                                                                                      |
|------------|----------------------------------------------------------------------------------------------|
| `users`    | id, username, email, role, created_at                                                        |
| `projects` | id, name, description, owner_id, status, created_at                                         |
| `tasks`    | id, title, description, status, assigned_to, priority, created_at, updated_at, project_id   |
| `comments` | id, task_id, user_id, content, created_at                                                    |

```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE,
    role TEXT DEFAULT 'member' CHECK(role IN ('admin', 'member', 'viewer')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT DEFAULT '',
    owner_id INTEGER,
    status TEXT DEFAULT 'active' CHECK(status IN ('active', 'archived')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    status TEXT DEFAULT 'pending'
        CHECK(status IN ('pending', 'in_progress', 'completed', 'cancelled')),
    assigned_to INTEGER,
    priority TEXT DEFAULT 'medium'
        CHECK(priority IN ('low', 'medium', 'high', 'critical')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    project_id INTEGER,
    FOREIGN KEY (assigned_to) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL
);

CREATE TABLE comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
```


---

## Execution and Sandboxing Layer

The execution layer is a separate component within the DB Agent that handles
the safe execution of parameterized queries. It is independent of the
query-generation module and enforces its own protections.

### Scope

| In Scope                                         | Out of Scope                          |
|--------------------------------------------------|---------------------------------------|
| Parameterized query execution                    | Natural-language to SQL translation   |
| Sandboxed SQLite database management             | Query optimization                    |
| Read-only connection enforcement                 | Connection pooling (production)       |
| Execution timeouts                               | Multi-database support                |
| Row-count limits                                 | ORM integration                       |
| Result formatting as JSON                        | Transaction management                |

### Files

```
db-agent/
  sandbox.py          -- Sandbox database lifecycle management
  executor.py         -- Core query execution engine
  executor_api.py     -- FastAPI HTTP wrapper (port 8013)
  test_executor.py    -- Execution layer tests
```

### Execution API (Port 8013)

| Method | Endpoint   | Description                              |
|--------|------------|------------------------------------------|
| `GET`  | `/health`  | Health check                             |
| `POST` | `/execute` | Execute a parameterized query            |

#### POST /execute

Request:
```json
{
  "query": "SELECT id, username FROM users WHERE role = ?",
  "parameters": ["admin"],
  "timeout": 10.0,
  "max_rows": 100,
  "enforce_read_only": null
}
```

Response:
```json
{
  "success": true,
  "query": "SELECT id, username FROM users WHERE role = ?",
  "parameters": ["admin"],
  "columns": ["id", "username"],
  "rows": [{"id": 1, "username": "admin_lead"}],
  "row_count": 1,
  "truncated": false,
  "execution_time_ms": 1.23,
  "error": null
}
```

### Protections

| Protection           | Description                                      |
|----------------------|--------------------------------------------------|
| **Read-only mode**   | SELECT queries use read-only connections by default. Write operations are blocked on read-only connections. |
| **Execution timeout**| Queries exceeding the timeout (default: 10s) are interrupted via SQLite progress handler. |
| **Row-count limit**  | Results are truncated to max_rows (default: 1000). The `truncated` flag indicates if truncation occurred. |
| **Sandboxed DB**     | Each execution creates a temporary SQLite database that is destroyed after use. |

### Running the Execution API

```bash
python executor_api.py
# Server starts at http://localhost:8013
```

### Running Execution Tests

```bash
python test_executor.py
```

### Integration with Query-Generation Module

The typical workflow:
1. Call the query-generation API (`POST /generate` on port 8012).
2. Receive the parameterized query and parameters.
3. Pass them to the execution API (`POST /execute` on port 8013).
4. Receive formatted results.

The query-generation module guarantees that all returned queries have passed
safety validation. The execution layer enforces additional runtime protections
(read-only connections, timeouts, row limits) as a defense-in-depth measure.

### Configuration

| Variable              | Default    | Description                      |
|-----------------------|------------|----------------------------------|
| `DB_EXECUTOR_HOST`    | `0.0.0.0` | Execution API bind address       |
| `DB_EXECUTOR_PORT`    | `8013`     | Execution API port               |

