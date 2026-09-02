"""
DB Agent -- Query Execution Engine.

Accepts a parameterized query and its parameters, executes it against
a sandboxed database, and returns formatted results. Enforces protections
independent of the query-generation layer:

- Read-only connections for SELECT queries
- Execution timeouts
- Row-count limits
"""

import signal
import sqlite3
import threading
import time
from typing import Any

from sandbox import SandboxDatabase


# ---------------------------------------------------------------------------
# Default limits
# ---------------------------------------------------------------------------

DEFAULT_TIMEOUT_SECONDS: float = 10.0
DEFAULT_MAX_ROWS: int = 1000


# ---------------------------------------------------------------------------
# Execution engine
# ---------------------------------------------------------------------------

def execute_query(
    query: str,
    parameters: list[Any] | None = None,
    sandbox: SandboxDatabase | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_rows: int = DEFAULT_MAX_ROWS,
    enforce_read_only: bool | None = None,
) -> dict:
    """Execute a parameterized query against a sandboxed database.

    Args:
        query: The SQL query to execute. Must use ? placeholders for
               parameterized values.
        parameters: List of parameter values matching the ? placeholders
                    in the query. Defaults to an empty list.
        sandbox: An existing SandboxDatabase to use. If None, a new
                 temporary sandbox is created and destroyed after execution.
        timeout: Maximum execution time in seconds. Queries exceeding
                 this limit are interrupted.
        max_rows: Maximum number of rows to return. Additional rows are
                  silently truncated.
        enforce_read_only: If True, use a read-only connection (only
                          SELECT queries succeed). If None, read-only
                          mode is auto-detected based on the query type.

    Returns:
        A dict with keys:
        - success: bool
        - query: the executed query
        - parameters: the parameters used
        - columns: list of column names (for SELECT queries)
        - rows: list of row dicts (for SELECT queries)
        - row_count: number of rows returned or affected
        - truncated: whether the result was truncated by max_rows
        - execution_time_ms: query execution time in milliseconds
        - error: error message (if success is False)
    """
    if parameters is None:
        parameters = []

    # Auto-detect read-only mode if not specified.
    query_upper = query.strip().upper()
    is_select = query_upper.startswith("SELECT")
    if enforce_read_only is None:
        enforce_read_only = is_select

    # Determine if we own the sandbox (and must clean it up).
    own_sandbox = sandbox is None
    if own_sandbox:
        sandbox = SandboxDatabase(read_only=enforce_read_only)

    result = {
        "success": False,
        "query": query,
        "parameters": parameters,
        "columns": [],
        "rows": [],
        "row_count": 0,
        "truncated": False,
        "execution_time_ms": 0.0,
        "error": None,
    }

    try:
        conn = sandbox.connection

        # Execute with timeout enforcement.
        start_time = time.perf_counter()

        # Set a progress handler that checks elapsed time.
        # The handler is called approximately every N virtual machine
        # instructions. We use 1000 instructions as the interval.
        timed_out = False

        def _progress_handler():
            nonlocal timed_out
            elapsed = time.perf_counter() - start_time
            if elapsed > timeout:
                timed_out = True
                return 1  # Non-zero return interrupts the query.
            return 0

        conn.set_progress_handler(_progress_handler, 1000)

        try:
            cursor = conn.execute(query, parameters)
        except sqlite3.OperationalError as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            result["execution_time_ms"] = round(elapsed_ms, 2)

            if timed_out or "interrupted" in str(exc).lower():
                result["error"] = (
                    f"Query execution timed out after {timeout} seconds."
                )
            elif "readonly" in str(exc).lower() or "attempt to write" in str(exc).lower():
                result["error"] = (
                    "Write operation blocked: connection is read-only."
                )
            else:
                result["error"] = str(exc)
            return result
        except sqlite3.Error as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            result["execution_time_ms"] = round(elapsed_ms, 2)
            result["error"] = str(exc)
            return result
        finally:
            # Remove the progress handler.
            conn.set_progress_handler(None, 0)

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        result["execution_time_ms"] = round(elapsed_ms, 2)

        if timed_out:
            result["error"] = (
                f"Query execution timed out after {timeout} seconds."
            )
            return result

        # Process results.
        if is_select and cursor.description:
            result["columns"] = [desc[0] for desc in cursor.description]
            all_rows = cursor.fetchmany(max_rows + 1)

            if len(all_rows) > max_rows:
                all_rows = all_rows[:max_rows]
                result["truncated"] = True

            result["rows"] = [dict(row) for row in all_rows]
            result["row_count"] = len(result["rows"])
        else:
            result["row_count"] = cursor.rowcount

        result["success"] = True

    except Exception as exc:
        result["error"] = str(exc)
    finally:
        if own_sandbox:
            sandbox.close()

    return result


def execute_query_batch(
    queries: list[dict],
    sandbox: SandboxDatabase | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_rows: int = DEFAULT_MAX_ROWS,
) -> list[dict]:
    """Execute multiple queries sequentially against a shared sandbox.

    Args:
        queries: List of dicts, each with 'query' and optional 'parameters'.
        sandbox: An existing SandboxDatabase. If None, a new one is created.
        timeout: Timeout per query in seconds.
        max_rows: Max rows per query result.

    Returns:
        List of result dicts, one per query.
    """
    own_sandbox = sandbox is None
    if own_sandbox:
        sandbox = SandboxDatabase(read_only=False)

    results = []
    try:
        for q in queries:
            result = execute_query(
                query=q["query"],
                parameters=q.get("parameters", []),
                sandbox=sandbox,
                timeout=timeout,
                max_rows=max_rows,
                enforce_read_only=q.get("enforce_read_only"),
            )
            results.append(result)
    finally:
        if own_sandbox:
            sandbox.close()

    return results
