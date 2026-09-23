"""
DB Agent Configuration.

Centralizes all configurable parameters for the query-generation module.
"""

import os

# ---------------------------------------------------------------------------
# Ollama LLM settings
# ---------------------------------------------------------------------------
OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen3-coder:latest")
GROQ_MODEL: str = os.getenv(
    "DB_AGENT_GROQ_MODEL", os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
)
OLLAMA_KEEP_ALIVE: str = os.getenv("OLLAMA_KEEP_ALIVE", "30m")
OLLAMA_CONTEXT_SIZE: int = int(os.getenv("OLLAMA_CONTEXT_SIZE", "2048"))

# ---------------------------------------------------------------------------
# LLM generation parameters
# ---------------------------------------------------------------------------
TEMPERATURE: float = float(os.getenv("DB_AGENT_TEMPERATURE", "0.1"))
MAX_TOKENS: int = int(os.getenv("DB_AGENT_MAX_TOKENS", "800"))

# ---------------------------------------------------------------------------
# API server
# ---------------------------------------------------------------------------
API_HOST: str = os.getenv("DB_AGENT_HOST", "0.0.0.0")
API_PORT: int = int(os.getenv("DB_AGENT_PORT", "8012"))

# ---------------------------------------------------------------------------
# Database schema description for query generation
# Schema mirrors target-app/app.py SCHEMA_SQL exactly.
# Update both locations if the target-app schema changes.
# ---------------------------------------------------------------------------
DEFAULT_SCHEMA = {
    "users": {
        "columns": ["id", "username", "email", "role", "created_at"],
        "description": "Application users with roles: admin, member, viewer",
        "primary_key": "id",
    },
    "projects": {
        "columns": ["id", "name", "description", "owner_id", "status", "created_at"],
        "description": "Projects grouping related tasks. status: active, archived. owner_id FK -> users.id",
        "primary_key": "id",
        "foreign_keys": ["owner_id -> users.id"],
    },
    "tasks": {
        "columns": ["id", "title", "description", "status", "assigned_to", "priority", "created_at", "updated_at", "project_id"],
        "description": "Tasks with status: pending, in_progress, completed, cancelled. priority: low, medium, high, critical. assigned_to FK -> users.id. project_id FK -> projects.id",
        "primary_key": "id",
        "foreign_keys": ["assigned_to -> users.id", "project_id -> projects.id"],
    },
    "comments": {
        "columns": ["id", "task_id", "user_id", "content", "created_at"],
        "description": "Comments on tasks. task_id FK -> tasks.id. user_id FK -> users.id",
        "primary_key": "id",
        "foreign_keys": ["task_id -> tasks.id", "user_id -> users.id"],
    },
}

# SQL DDL representation — used by query_generator and the /schema endpoint.
# Schema mirrors target-app/app.py SCHEMA_SQL exactly.
# Update both locations if the target-app schema changes.
PLACEHOLDER_SCHEMA: str = """
-- Users table
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE,
    role TEXT DEFAULT 'member' CHECK(role IN ('admin', 'member', 'viewer')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Projects table
CREATE TABLE projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT DEFAULT '',
    owner_id INTEGER,
    status TEXT DEFAULT 'active' CHECK(status IN ('active', 'archived')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE SET NULL
);

-- Tasks table
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

-- Comments table
CREATE TABLE comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
"""
