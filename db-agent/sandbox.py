"""
DB Agent -- Sandbox Management.

Creates and manages isolated SQLite databases for safe query execution.
Handles database lifecycle, schema initialization, and seed data loading.
"""

import os
import sqlite3
import tempfile
from pathlib import Path


# Default schema and seed data (same as the target-app schema).
DEFAULT_SCHEMA = """\
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE,
    role TEXT DEFAULT 'member' CHECK(role IN ('admin', 'member', 'viewer')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'in_progress', 'completed', 'cancelled')),
    assigned_to INTEGER,
    priority TEXT DEFAULT 'medium' CHECK(priority IN ('low', 'medium', 'high', 'critical')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (assigned_to) REFERENCES users(id) ON DELETE SET NULL
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

DEFAULT_SEED_DATA = """\
INSERT INTO users (username, email, role) VALUES ('admin_lead', 'admin@example.com', 'admin');
INSERT INTO users (username, email, role) VALUES ('dev_alpha', 'dev.alpha@example.com', 'member');
INSERT INTO users (username, email, role) VALUES ('dev_beta', 'dev.beta@example.com', 'member');
INSERT INTO users (username, email, role) VALUES ('qa_tester', 'qa@example.com', 'member');
INSERT INTO users (username, email, role) VALUES ('stakeholder', 'stakeholder@example.com', 'viewer');

INSERT INTO tasks (title, description, status, assigned_to, priority) VALUES
    ('Set up CI/CD pipeline', 'Configure CI/CD workflows.', 'completed', 1, 'high');
INSERT INTO tasks (title, description, status, assigned_to, priority) VALUES
    ('Design database schema', 'Create the initial schema.', 'completed', 2, 'critical');
INSERT INTO tasks (title, description, status, assigned_to, priority) VALUES
    ('Implement user authentication', 'Add JWT authentication.', 'in_progress', 2, 'high');
INSERT INTO tasks (title, description, status, assigned_to, priority) VALUES
    ('Build task list UI', 'Create a React component for tasks.', 'in_progress', 3, 'medium');
INSERT INTO tasks (title, description, status, assigned_to, priority) VALUES
    ('Write API integration tests', 'Cover all REST endpoints.', 'pending', 4, 'high');

INSERT INTO comments (task_id, user_id, content) VALUES
    (1, 2, 'Pipeline configuration is complete.');
INSERT INTO comments (task_id, user_id, content) VALUES
    (2, 1, 'Approved the schema design.');
INSERT INTO comments (task_id, user_id, content) VALUES
    (3, 2, 'JWT implementation is in progress.');
"""


class SandboxDatabase:
    """Manages an isolated SQLite database for sandboxed query execution.

    Each sandbox instance creates a temporary database file, initializes
    the schema, and loads seed data. The database is destroyed when the
    sandbox is closed.
    """

    def __init__(
        self,
        schema: str | None = None,
        seed_data: str | None = None,
        read_only: bool = False,
    ):
        """Initialize a sandboxed database.

        Args:
            schema: SQL DDL to create tables. Defaults to the standard
                    task-management schema.
            seed_data: SQL INSERT statements for seed data. Defaults to
                       standard seed data.
            read_only: If True, the connection is opened in read-only mode
                       using a URI with mode=ro. Write operations will
                       raise an error.
        """
        self._schema = schema or DEFAULT_SCHEMA
        self._seed_data = seed_data or DEFAULT_SEED_DATA
        self._read_only = read_only
        self._tmp_file = None
        self._conn = None
        self._db_path = None
        self._setup()

    def _setup(self):
        """Create the temporary database, initialize schema and seed data."""
        # Create a temporary file for the database.
        self._tmp_file = tempfile.NamedTemporaryFile(
            suffix=".db", delete=False
        )
        self._tmp_file.close()
        self._db_path = self._tmp_file.name

        # Initialize with a writable connection first.
        init_conn = sqlite3.connect(self._db_path)
        init_conn.execute("PRAGMA foreign_keys = ON")
        init_conn.executescript(self._schema)
        init_conn.executescript(self._seed_data)
        init_conn.close()

        # Open the working connection.
        if self._read_only:
            # Use SQLite URI mode for read-only access.
            uri = f"file:{self._db_path}?mode=ro"
            self._conn = sqlite3.connect(
                uri, uri=True, check_same_thread=False
            )
        else:
            self._conn = sqlite3.connect(
                self._db_path, check_same_thread=False
            )

        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")

    @property
    def connection(self) -> sqlite3.Connection:
        """Return the database connection."""
        if self._conn is None:
            raise RuntimeError("Sandbox has been closed.")
        return self._conn

    @property
    def db_path(self) -> str:
        """Return the path to the database file."""
        return self._db_path

    @property
    def is_read_only(self) -> bool:
        """Return whether this sandbox is in read-only mode."""
        return self._read_only

    def close(self):
        """Close the connection and delete the temporary database file."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

        if self._db_path and os.path.exists(self._db_path):
            try:
                os.unlink(self._db_path)
            except OSError:
                pass
            self._db_path = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def __del__(self):
        self.close()
