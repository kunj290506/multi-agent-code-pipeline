"""
Sample Application -- User Service.

This module provides a FastAPI-based REST API for managing users in a
task-management application. It connects to a SQLite database and
exposes CRUD endpoints.
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import sqlite3
from typing import Optional

app = FastAPI(title="Task Manager API", version="1.0.0")

DATABASE_PATH = "taskmanager.db"


class User(BaseModel):
    """Schema for a user record."""
    id: Optional[int] = None
    username: str
    email: str
    role: str = "member"


class Task(BaseModel):
    """Schema for a task record."""
    id: Optional[int] = None
    title: str
    description: str = ""
    status: str = "pending"
    assigned_to: Optional[int] = None
    priority: str = "medium"


def get_db_connection():
    """Create and return a database connection."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_database():
    """Initialize the database with required tables."""
    conn = get_db_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL UNIQUE,
            role TEXT DEFAULT 'member',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            assigned_to INTEGER,
            priority TEXT DEFAULT 'medium',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (assigned_to) REFERENCES users(id)
        )
    """)
    conn.commit()
    conn.close()


@app.on_event("startup")
def startup():
    init_database()


@app.get("/users")
def list_users():
    """Return all users."""
    conn = get_db_connection()
    users = conn.execute("SELECT * FROM users").fetchall()
    conn.close()
    return [dict(u) for u in users]


@app.post("/users")
def create_user(user: User):
    """Create a new user."""
    conn = get_db_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO users (username, email, role) VALUES (?, ?, ?)",
            (user.username, user.email, user.role),
        )
        conn.commit()
        user.id = cursor.lastrowid
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        conn.close()
    return user


@app.get("/tasks")
def list_tasks():
    """Return all tasks."""
    conn = get_db_connection()
    tasks = conn.execute("SELECT * FROM tasks").fetchall()
    conn.close()
    return [dict(t) for t in tasks]


@app.post("/tasks")
def create_task(task: Task):
    """Create a new task."""
    conn = get_db_connection()
    cursor = conn.execute(
        "INSERT INTO tasks (title, description, status, assigned_to, priority) "
        "VALUES (?, ?, ?, ?, ?)",
        (task.title, task.description, task.status, task.assigned_to, task.priority),
    )
    conn.commit()
    task.id = cursor.lastrowid
    conn.close()
    return task


@app.get("/tasks/{task_id}")
def get_task(task_id: int):
    """Return a single task by ID."""
    conn = get_db_connection()
    task = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    conn.close()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return dict(task)
