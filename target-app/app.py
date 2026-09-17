"""
Target Application -- Task Manager REST API.

A sample backend application built with FastAPI that provides CRUD
endpoints for managing users, tasks, and comments. Uses a local SQLite
database for persistence.

This application serves as the reference codebase that the RAG agent
indexes and the Code-Gen agent generates additions for.
"""

import logging
import os
import sqlite3
from contextlib import contextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("target-app")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DATABASE_PATH: str = os.getenv(
    "TARGET_APP_DB",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "taskmanager.db"),
)
API_HOST: str = os.getenv("TARGET_APP_HOST", "0.0.0.0")
API_PORT: int = int(os.getenv("TARGET_APP_PORT", "8000"))

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE,
    role TEXT DEFAULT 'member' CHECK(role IN ('admin', 'member', 'viewer')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT DEFAULT '',
    owner_id INTEGER,
    status TEXT DEFAULT 'active' CHECK(status IN ('active', 'archived')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS tasks (
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

CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
"""

SEED_SQL = """\
INSERT OR IGNORE INTO users (username, email, role)
    VALUES ('admin_lead', 'admin@example.com', 'admin');
INSERT OR IGNORE INTO users (username, email, role)
    VALUES ('dev_alpha', 'dev.alpha@example.com', 'member');
INSERT OR IGNORE INTO users (username, email, role)
    VALUES ('dev_beta', 'dev.beta@example.com', 'member');
INSERT OR IGNORE INTO users (username, email, role)
    VALUES ('qa_tester', 'qa@example.com', 'member');
INSERT OR IGNORE INTO users (username, email, role)
    VALUES ('stakeholder', 'stakeholder@example.com', 'viewer');

INSERT OR IGNORE INTO tasks (title, description, status, assigned_to, priority)
    VALUES ('Set up CI/CD pipeline', 'Configure CI/CD workflows.',
            'completed', 1, 'high');
INSERT OR IGNORE INTO tasks (title, description, status, assigned_to, priority)
    VALUES ('Design database schema', 'Create the initial schema.',
            'completed', 2, 'critical');
INSERT OR IGNORE INTO tasks (title, description, status, assigned_to, priority)
    VALUES ('Implement user authentication', 'Add JWT authentication.',
            'in_progress', 2, 'high');
INSERT OR IGNORE INTO tasks (title, description, status, assigned_to, priority)
    VALUES ('Build task list UI', 'Create a React component for tasks.',
            'in_progress', 3, 'medium');
INSERT OR IGNORE INTO tasks (title, description, status, assigned_to, priority)
    VALUES ('Write API integration tests', 'Cover all REST endpoints.',
            'pending', 4, 'high');

INSERT OR IGNORE INTO comments (task_id, user_id, content)
    VALUES (1, 2, 'Pipeline configuration is complete.');
INSERT OR IGNORE INTO comments (task_id, user_id, content)
    VALUES (2, 1, 'Approved the schema design.');
INSERT OR IGNORE INTO comments (task_id, user_id, content)
    VALUES (3, 2, 'JWT implementation is in progress.');

INSERT OR IGNORE INTO projects (name, description, owner_id, status)
    VALUES ('Backend API', 'Core REST API development tasks.', 1, 'active');
INSERT OR IGNORE INTO projects (name, description, owner_id, status)
    VALUES ('Frontend UI', 'React frontend components and pages.', 2, 'active');

-- Update existing tasks to link to projects
UPDATE tasks SET project_id = 1 WHERE title IN ('Set up CI/CD pipeline', 'Design database schema', 'Implement user authentication', 'Write API integration tests');
UPDATE tasks SET project_id = 2 WHERE title = 'Build task list UI';
"""


@contextmanager
def get_db():
    """Yield a database connection with row_factory set to sqlite3.Row."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()


def init_database() -> None:
    """Create tables and insert seed data if the database is empty."""
    logger.info("Initializing database at %s", DATABASE_PATH)
    with get_db() as conn:
        conn.executescript(SCHEMA_SQL)
        conn.executescript(SEED_SQL)
        conn.commit()
    logger.info("Database initialization complete.")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class UserCreate(BaseModel):
    """Request body for creating a user."""
    username: str = Field(..., min_length=1, max_length=50)
    email: str = Field(..., min_length=3, max_length=120)
    role: str = Field(default="member")


class UserResponse(BaseModel):
    """Response model for a user record."""
    id: int
    username: str
    email: str
    role: str
    created_at: str


class TaskCreate(BaseModel):
    """Request body for creating a task."""
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="")
    status: str = Field(default="pending")
    assigned_to: Optional[int] = None
    priority: str = Field(default="medium")


class TaskUpdate(BaseModel):
    """Request body for updating a task."""
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    assigned_to: Optional[int] = None
    priority: Optional[str] = None


class TaskResponse(BaseModel):
    """Response model for a task record."""
    id: int
    title: str
    description: str
    status: str
    assigned_to: Optional[int]
    priority: str
    created_at: str
    updated_at: str
    project_id: Optional[int]


class CommentCreate(BaseModel):
    """Request body for creating a comment."""
    task_id: int
    user_id: int
    content: str = Field(..., min_length=1)


class CommentResponse(BaseModel):
    """Response model for a comment record."""
    id: int
    task_id: int
    user_id: int
    content: str
    created_at: str


class ProjectCreate(BaseModel):
    """Request body for creating a project."""
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="")
    owner_id: Optional[int] = None
    status: str = Field(default="active")


class ProjectUpdate(BaseModel):
    """Request body for updating a project."""
    name: Optional[str] = None
    description: Optional[str] = None
    owner_id: Optional[int] = None
    status: Optional[str] = None


class ProjectResponse(BaseModel):
    """Response model for a project record."""
    id: int
    name: str
    description: str
    owner_id: Optional[int]
    status: str
    created_at: str


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Task Manager API",
    description="Sample REST API for managing users, tasks, and comments.",
    version="1.0.0",
)


@app.on_event("startup")
def on_startup() -> None:
    """Initialize the database on application startup."""
    init_database()


# -- Health ------------------------------------------------------------------

@app.get("/health")
def health_check() -> dict:
    """Return service health status."""
    return {"status": "healthy", "service": "target-app"}


# -- Users -------------------------------------------------------------------

@app.get("/users", response_model=list[UserResponse])
def list_users() -> list[dict]:
    """Return all users."""
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY id").fetchall()
    return [dict(r) for r in rows]


@app.get("/users/{user_id}", response_model=UserResponse)
def get_user(user_id: int) -> dict:
    """Return a single user by ID."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found.")
    return dict(row)


@app.post("/users", response_model=UserResponse, status_code=201)
def create_user(body: UserCreate) -> dict:
    """Create a new user."""
    with get_db() as conn:
        try:
            cursor = conn.execute(
                "INSERT INTO users (username, email, role) VALUES (?, ?, ?)",
                (body.username, body.email, body.role),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        row = conn.execute(
            "SELECT * FROM users WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
    logger.info("Created user id=%d username=%s", row["id"], row["username"])
    return dict(row)


# -- Tasks -------------------------------------------------------------------

@app.get("/tasks", response_model=list[TaskResponse])
def list_tasks(
    status: Optional[str] = None,
    priority: Optional[str] = None,
) -> list[dict]:
    """Return all tasks, optionally filtered by status or priority."""
    query = "SELECT * FROM tasks"
    params: list = []
    filters: list[str] = []
    if status:
        filters.append("status = ?")
        params.append(status)
    if priority:
        filters.append("priority = ?")
        params.append(priority)
    if filters:
        query += " WHERE " + " AND ".join(filters)
    query += " ORDER BY id"
    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


@app.get("/tasks/{task_id}", response_model=TaskResponse)
def get_task(task_id: int) -> dict:
    """Return a single task by ID."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Task not found.")
    return dict(row)


@app.post("/tasks", response_model=TaskResponse, status_code=201)
def create_task(body: TaskCreate) -> dict:
    """Create a new task."""
    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO tasks (title, description, status, assigned_to, priority) "
            "VALUES (?, ?, ?, ?, ?)",
            (body.title, body.description, body.status,
             body.assigned_to, body.priority),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
    logger.info("Created task id=%d title=%s", row["id"], row["title"])
    return dict(row)


@app.put("/tasks/{task_id}", response_model=TaskResponse)
def update_task(task_id: int, body: TaskUpdate) -> dict:
    """Update an existing task."""
    with get_db() as conn:
        existing = conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Task not found.")
        updates = {
            k: v for k, v in body.model_dump().items() if v is not None
        }
        if not updates:
            return dict(existing)
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [task_id]
        conn.execute(
            f"UPDATE tasks SET {set_clause}, updated_at = CURRENT_TIMESTAMP "
            f"WHERE id = ?",
            values,
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
    logger.info("Updated task id=%d", task_id)
    return dict(row)


@app.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: int) -> None:
    """Delete a task by ID."""
    with get_db() as conn:
        existing = conn.execute(
            "SELECT id FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Task not found.")
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()
    logger.info("Deleted task id=%d", task_id)


# -- Comments ----------------------------------------------------------------

@app.get("/tasks/{task_id}/comments", response_model=list[CommentResponse])
def list_comments(task_id: int) -> list[dict]:
    """Return all comments for a given task."""
    with get_db() as conn:
        task = conn.execute(
            "SELECT id FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found.")
        rows = conn.execute(
            "SELECT * FROM comments WHERE task_id = ? ORDER BY id",
            (task_id,),
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/comments", response_model=CommentResponse, status_code=201)
def create_comment(body: CommentCreate) -> dict:
    """Create a new comment on a task."""
    with get_db() as conn:
        task = conn.execute(
            "SELECT id FROM tasks WHERE id = ?", (body.task_id,)
        ).fetchone()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found.")
        user = conn.execute(
            "SELECT id FROM users WHERE id = ?", (body.user_id,)
        ).fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="User not found.")
        cursor = conn.execute(
            "INSERT INTO comments (task_id, user_id, content) VALUES (?, ?, ?)",
            (body.task_id, body.user_id, body.content),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM comments WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
    logger.info("Created comment id=%d on task=%d", row["id"], row["task_id"])
    return dict(row)


# -- Projects ----------------------------------------------------------------

@app.get("/projects", response_model=list[ProjectResponse])
def list_projects(status: Optional[str] = None) -> list[dict]:
    """Return all projects, optionally filtered by status."""
    query = "SELECT * FROM projects"
    params: list = []
    if status:
        query += " WHERE status = ?"
        params.append(status)
    query += " ORDER BY id"
    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


@app.get("/projects/{project_id}", response_model=ProjectResponse)
def get_project(project_id: int) -> dict:
    """Return a single project by ID."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Project not found.")
    return dict(row)


@app.post("/projects", response_model=ProjectResponse, status_code=201)
def create_project(body: ProjectCreate) -> dict:
    """Create a new project."""
    with get_db() as conn:
        try:
            cursor = conn.execute(
                "INSERT INTO projects (name, description, owner_id, status) VALUES (?, ?, ?, ?)",
                (body.name, body.description, body.owner_id, body.status),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        row = conn.execute(
            "SELECT * FROM projects WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
    logger.info("Created project id=%d name=%s", row["id"], row["name"])
    return dict(row)


@app.put("/projects/{project_id}", response_model=ProjectResponse)
def update_project(project_id: int, body: ProjectUpdate) -> dict:
    """Update an existing project."""
    with get_db() as conn:
        existing = conn.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Project not found.")
        updates = {k: v for k, v in body.model_dump().items() if v is not None}
        if not updates:
            return dict(existing)
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [project_id]
        conn.execute(
            f"UPDATE projects SET {set_clause} WHERE id = ?", values
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
    logger.info("Updated project id=%d", project_id)
    return dict(row)


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host=API_HOST,
        port=API_PORT,
        reload=True,
    )
