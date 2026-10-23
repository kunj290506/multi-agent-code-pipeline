# backend/store.py
"""SQLite storage for sessions, message history, audit logs, approvals, file backups, and codebase index."""

import json
import os
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional

DB_FILE = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "assistant.db"))


def get_db(db_path: str = DB_FILE) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Ensure tables exist
    with conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            workspace_path TEXT NOT NULL,
            model TEXT NOT NULL,
            auto_approve_writes INTEGER DEFAULT 0,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            metadata_json TEXT,
            created_at REAL NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            tool_name TEXT NOT NULL,
            arguments TEXT,
            status TEXT NOT NULL,
            approval_id TEXT,
            result TEXT,
            timestamp REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS approvals (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            tool_name TEXT NOT NULL,
            arguments TEXT,
            status TEXT NOT NULL,
            reason TEXT,
            created_at REAL NOT NULL,
            resolved_at REAL
        );
        CREATE TABLE IF NOT EXISTS backups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT NOT NULL,
            original_content TEXT NOT NULL,
            new_content TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS code_index (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            mtime REAL NOT NULL,
            UNIQUE(file_path, chunk_index)
        );
        """)
    return conn


def init_db(db_path: str = DB_FILE) -> None:
    conn = get_db(db_path)
    conn.close()


def create_session(
    name: str = "New Session",
    workspace_path: str = "",
    model: str = "qwen2.5:7b-instruct-q4_K_M",
    auto_approve_writes: bool = True,
    db_path: str = DB_FILE,
) -> Dict[str, Any]:
    session_id = str(uuid.uuid4())
    now = time.time()
    if not workspace_path:
        workspace_path = os.path.abspath(os.environ.get("WORKSPACE_DIR", "./workspace"))
    conn = get_db(db_path)
    with conn:
        conn.execute(
            """
            INSERT INTO sessions (id, name, workspace_path, model, auto_approve_writes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, name, workspace_path, model, 1 if auto_approve_writes else 0, now, now),
        )
    conn.close()
    return get_session(session_id, db_path)


def get_session(session_id: str, db_path: str = DB_FILE) -> Optional[Dict[str, Any]]:
    conn = get_db(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    data = dict(row)
    data["auto_approve_writes"] = bool(data["auto_approve_writes"])
    return data


def list_sessions(db_path: str = DB_FILE) -> List[Dict[str, Any]]:
    conn = get_db(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM sessions ORDER BY updated_at DESC")
    rows = cur.fetchall()
    conn.close()
    res = []
    for r in rows:
        d = dict(r)
        d["auto_approve_writes"] = bool(d["auto_approve_writes"])
        res.append(d)
    return res


def delete_session(session_id: str, db_path: str = DB_FILE) -> bool:
    conn = get_db(db_path)
    with conn:
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM approvals WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM audit_logs WHERE session_id = ?", (session_id,))
        cur = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        deleted = cur.rowcount > 0
    conn.close()
    return deleted


def update_session(
    session_id: str,
    name: Optional[str] = None,
    workspace_path: Optional[str] = None,
    model: Optional[str] = None,
    auto_approve_writes: Optional[bool] = None,
    db_path: str = DB_FILE,
) -> Optional[Dict[str, Any]]:
    conn = get_db(db_path)
    now = time.time()
    fields = ["updated_at = ?"]
    params: List[Any] = [now]
    if name is not None:
        fields.append("name = ?")
        params.append(name)
    if workspace_path is not None:
        fields.append("workspace_path = ?")
        params.append(workspace_path)
    if model is not None:
        fields.append("model = ?")
        params.append(model)
    if auto_approve_writes is not None:
        fields.append("auto_approve_writes = ?")
        params.append(1 if auto_approve_writes else 0)
    params.append(session_id)
    with conn:
        conn.execute(f"UPDATE sessions SET {', '.join(fields)} WHERE id = ?", params)
    conn.close()
    return get_session(session_id, db_path)


def add_message(
    session_id: str,
    role: str,
    content: str,
    metadata: Optional[Dict[str, Any]] = None,
    db_path: str = DB_FILE,
) -> Dict[str, Any]:
    msg_id = str(uuid.uuid4())
    now = time.time()
    meta_str = json.dumps(metadata) if metadata else None
    conn = get_db(db_path)
    with conn:
        conn.execute(
            """
            INSERT INTO messages (id, session_id, role, content, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (msg_id, session_id, role, content, meta_str, now),
        )
        conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
    conn.close()
    return {
        "id": msg_id,
        "session_id": session_id,
        "role": role,
        "content": content,
        "metadata": metadata or {},
        "created_at": now,
    }


def get_messages(session_id: str, limit: Optional[int] = None, db_path: str = DB_FILE) -> List[Dict[str, Any]]:
    conn = get_db(db_path)
    cur = conn.cursor()
    query = "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at ASC"
    if limit:
        query += f" LIMIT {int(limit)}"
    cur.execute(query, (session_id,))
    rows = cur.fetchall()
    conn.close()
    msgs = []
    for r in rows:
        d = dict(r)
        d["metadata"] = json.loads(d["metadata_json"]) if d["metadata_json"] else {}
        msgs.append(d)
    return msgs


def add_audit_log(
    session_id: Optional[str],
    tool_name: str,
    arguments: Any,
    status: str,
    result: str = "",
    approval_id: Optional[str] = None,
    db_path: str = DB_FILE,
) -> None:
    conn = get_db(db_path)
    args_str = json.dumps(arguments) if isinstance(arguments, (dict, list)) else str(arguments)
    with conn:
        conn.execute(
            """
            INSERT INTO audit_logs (session_id, tool_name, arguments, status, approval_id, result, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, tool_name, args_str, status, approval_id, result[:1000], time.time()),
        )
    conn.close()


def get_audit_logs(session_id: Optional[str] = None, limit: int = 100, db_path: str = DB_FILE) -> List[Dict[str, Any]]:
    conn = get_db(db_path)
    cur = conn.cursor()
    if session_id:
        cur.execute("SELECT * FROM audit_logs WHERE session_id = ? ORDER BY timestamp DESC LIMIT ?", (session_id, limit))
    else:
        cur.execute("SELECT * FROM audit_logs ORDER BY timestamp DESC LIMIT ?", (limit,))
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def create_approval(
    session_id: str,
    tool_name: str,
    arguments: Any,
    reason: str = "",
    db_path: str = DB_FILE,
) -> Dict[str, Any]:
    approval_id = str(uuid.uuid4())
    now = time.time()
    args_str = json.dumps(arguments) if isinstance(arguments, (dict, list)) else str(arguments)
    conn = get_db(db_path)
    with conn:
        conn.execute(
            """
            INSERT INTO approvals (id, session_id, tool_name, arguments, status, reason, created_at)
            VALUES (?, ?, ?, ?, 'pending', ?, ?)
            """,
            (approval_id, session_id, tool_name, args_str, reason, now),
        )
    conn.close()
    return {
        "id": approval_id,
        "session_id": session_id,
        "tool_name": tool_name,
        "arguments": arguments,
        "status": "pending",
        "reason": reason,
        "created_at": now,
    }


def get_approval(approval_id: str, db_path: str = DB_FILE) -> Optional[Dict[str, Any]]:
    conn = get_db(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    try:
        d["arguments"] = json.loads(d["arguments"])
    except Exception:
        pass
    return d


def resolve_approval(approval_id: str, status: str, db_path: str = DB_FILE) -> bool:
    conn = get_db(db_path)
    now = time.time()
    with conn:
        cur = conn.execute(
            "UPDATE approvals SET status = ?, resolved_at = ? WHERE id = ? AND status = 'pending'",
            (status, now, approval_id),
        )
        updated = cur.rowcount > 0
    conn.close()
    return updated


def save_file_backup(file_path: str, original_content: str, new_content: str, db_path: str = DB_FILE) -> None:
    conn = get_db(db_path)
    with conn:
        conn.execute(
            """
            INSERT INTO backups (file_path, original_content, new_content, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (file_path, original_content, new_content, time.time()),
        )
    conn.close()


def get_last_backup(file_path: str, db_path: str = DB_FILE) -> Optional[Dict[str, Any]]:
    conn = get_db(db_path)
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM backups WHERE file_path = ? ORDER BY id DESC LIMIT 1",
        (file_path,),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def delete_last_backup(backup_id: int, db_path: str = DB_FILE) -> None:
    conn = get_db(db_path)
    with conn:
        conn.execute("DELETE FROM backups WHERE id = ?", (backup_id,))
    conn.close()


def upsert_code_chunks(file_path: str, chunks: List[str], mtime: float, db_path: str = DB_FILE) -> None:
    conn = get_db(db_path)
    with conn:
        conn.execute("DELETE FROM code_index WHERE file_path = ?", (file_path,))
        for idx, chunk in enumerate(chunks):
            conn.execute(
                """
                INSERT INTO code_index (file_path, chunk_index, content, mtime)
                VALUES (?, ?, ?, ?)
                """,
                (file_path, idx, chunk, mtime),
            )
    conn.close()


def search_keyword_index(query: str, limit: int = 10, db_path: str = DB_FILE) -> List[Dict[str, Any]]:
    conn = get_db(db_path)
    cur = conn.cursor()
    terms = [t.strip().lower() for t in query.split() if len(t.strip()) > 1]
    if not terms:
        terms = [query.lower()]
    like_clauses = " OR ".join(["LOWER(content) LIKE ?" for _ in terms])
    params = [f"%{t}%" for t in terms]
    sql = f"SELECT file_path, chunk_index, content FROM code_index WHERE {like_clauses} LIMIT ?"
    params.append(limit)
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]
