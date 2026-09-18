import sqlite3
from typing import Any

def execute_query(db_path: str, query: str, parameters: tuple = ()) -> list[dict[str, Any]]:
    """Execute a read query and return rows as a list of dicts."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(query, parameters)
        return [dict(row) for row in cursor.fetchall()]

def execute_write(db_path: str, query: str, parameters: tuple = ()) -> int:
    """Execute a write query (INSERT/UPDATE) and return lastrowid."""
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(query, parameters)
        conn.commit()
        return cursor.lastrowid
