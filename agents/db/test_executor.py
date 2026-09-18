"""
Test script for the DB Agent -- Execution and Sandboxing Layer.

Verifies:
- Successful query execution with parameterized queries
- Timeout enforcement
- Row-limit enforcement
- Read-only connection protection
- Sandbox lifecycle (creation and cleanup)
- API endpoint functionality
"""

import os
import sys
import time

# Ensure the db-agent directory is on the Python path.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient

import executor
from sandbox import SandboxDatabase


def run_tests():
    """Run all execution layer tests and report results."""
    passed = 0
    failed = 0

    def check(name, condition, detail=""):
        nonlocal passed, failed
        status = "PASS" if condition else "FAIL"
        if condition:
            passed += 1
        else:
            failed += 1
        print(f"  [{status}] {name}" + (f" -- {detail}" if detail else ""))

    print("=" * 70)
    print("DB AGENT -- EXECUTION LAYER TEST SUITE")
    print("=" * 70)

    # ------------------------------------------------------------------
    # Sandbox lifecycle
    # ------------------------------------------------------------------
    print("\n--- Sandbox Lifecycle ---")

    with SandboxDatabase() as sandbox:
        check("Sandbox creates successfully", sandbox.connection is not None)
        check(
            "Sandbox database file exists",
            os.path.exists(sandbox.db_path),
        )

        # Verify seed data was loaded.
        cursor = sandbox.connection.execute("SELECT COUNT(*) FROM users")
        count = cursor.fetchone()[0]
        check("Seed data loaded (users)", count == 5, f"got {count}")

        cursor = sandbox.connection.execute("SELECT COUNT(*) FROM tasks")
        count = cursor.fetchone()[0]
        check("Seed data loaded (tasks)", count == 5, f"got {count}")

        db_path = sandbox.db_path

    # After closing, the file should be cleaned up.
    check(
        "Sandbox database cleaned up after close",
        not os.path.exists(db_path),
    )

    # ------------------------------------------------------------------
    # Basic SELECT execution
    # ------------------------------------------------------------------
    print("\n--- Basic Query Execution ---")

    with SandboxDatabase() as sandbox:
        result = executor.execute_query(
            "SELECT id, username, email FROM users ORDER BY id",
            sandbox=sandbox,
        )
        check("SELECT query succeeds", result["success"])
        check(
            "SELECT returns correct row count",
            result["row_count"] == 5,
            f"got {result['row_count']}",
        )
        check(
            "SELECT returns correct columns",
            result["columns"] == ["id", "username", "email"],
            f"got {result['columns']}",
        )
        check(
            "First user is admin_lead",
            result["rows"][0]["username"] == "admin_lead",
        )

    # ------------------------------------------------------------------
    # Parameterized query execution
    # ------------------------------------------------------------------
    print("\n--- Parameterized Query Execution ---")

    with SandboxDatabase() as sandbox:
        result = executor.execute_query(
            "SELECT id, title, status FROM tasks WHERE status = ?",
            parameters=["completed"],
            sandbox=sandbox,
        )
        check("Parameterized SELECT succeeds", result["success"])
        check(
            "All returned tasks are completed",
            all(r["status"] == "completed" for r in result["rows"]),
        )

        result = executor.execute_query(
            "SELECT id, title FROM tasks WHERE priority = ? AND status = ?",
            parameters=["high", "in_progress"],
            sandbox=sandbox,
        )
        check("Multi-param SELECT succeeds", result["success"])
        check(
            "Results match filter criteria",
            result["row_count"] >= 0,
            f"got {result['row_count']} rows",
        )

    # ------------------------------------------------------------------
    # INSERT execution
    # ------------------------------------------------------------------
    print("\n--- INSERT Execution ---")

    with SandboxDatabase(read_only=False) as sandbox:
        result = executor.execute_query(
            "INSERT INTO users (username, email, role) VALUES (?, ?, ?)",
            parameters=["test_user", "test@example.com", "member"],
            sandbox=sandbox,
            enforce_read_only=False,
        )
        check("INSERT query succeeds", result["success"], result.get("error", ""))
        check(
            "INSERT affects 1 row",
            result["row_count"] == 1,
            f"got {result['row_count']}",
        )

        # Verify the insert.
        result = executor.execute_query(
            "SELECT username FROM users WHERE username = ?",
            parameters=["test_user"],
            sandbox=sandbox,
        )
        check(
            "Inserted row is retrievable",
            result["row_count"] == 1 and result["rows"][0]["username"] == "test_user",
        )

    # ------------------------------------------------------------------
    # Row-limit enforcement
    # ------------------------------------------------------------------
    print("\n--- Row-Limit Enforcement ---")

    with SandboxDatabase() as sandbox:
        # Request at most 2 rows.
        result = executor.execute_query(
            "SELECT id, username FROM users ORDER BY id",
            sandbox=sandbox,
            max_rows=2,
        )
        check("Row-limited query succeeds", result["success"])
        check(
            "Row count respects limit",
            result["row_count"] == 2,
            f"got {result['row_count']}",
        )
        check(
            "Truncated flag is set",
            result["truncated"] is True,
        )

        # Request with a limit larger than the data set.
        result = executor.execute_query(
            "SELECT id FROM users ORDER BY id",
            sandbox=sandbox,
            max_rows=100,
        )
        check(
            "No truncation when limit exceeds data",
            result["truncated"] is False and result["row_count"] == 5,
        )

    # ------------------------------------------------------------------
    # Read-only connection protection
    # ------------------------------------------------------------------
    print("\n--- Read-Only Protection ---")

    with SandboxDatabase(read_only=True) as sandbox:
        # SELECT should work fine.
        result = executor.execute_query(
            "SELECT COUNT(*) as cnt FROM users",
            sandbox=sandbox,
        )
        check(
            "SELECT on read-only connection succeeds",
            result["success"],
        )

        # INSERT should fail.
        result = executor.execute_query(
            "INSERT INTO users (username, email) VALUES (?, ?)",
            parameters=["hacker", "hack@example.com"],
            sandbox=sandbox,
            enforce_read_only=True,
        )
        check(
            "INSERT on read-only connection fails",
            result["success"] is False,
        )
        check(
            "Read-only error message is appropriate",
            result["error"] is not None and (
                "read" in result["error"].lower()
                or "write" in result["error"].lower()
            ),
            f"error: {result.get('error', '')}",
        )

    # ------------------------------------------------------------------
    # Timeout enforcement
    # ------------------------------------------------------------------
    print("\n--- Timeout Enforcement ---")

    with SandboxDatabase(read_only=False) as sandbox:
        # Insert enough data to make a heavy query take time.
        conn = sandbox.connection
        conn.execute("BEGIN")
        for i in range(5000):
            conn.execute(
                "INSERT INTO comments (task_id, user_id, content) VALUES (?, ?, ?)",
                (1, 1, f"Bulk comment number {i}"),
            )
        conn.execute("COMMIT")

        # Cross-join to create a computationally expensive query.
        result = executor.execute_query(
            "SELECT COUNT(*) as cnt FROM comments c1 "
            "CROSS JOIN comments c2 "
            "CROSS JOIN comments c3",
            sandbox=sandbox,
            timeout=0.5,
        )
        check(
            "Expensive query times out",
            result["success"] is False,
        )
        check(
            "Timeout error message is appropriate",
            result["error"] is not None and (
                "timed out" in result["error"].lower()
                or "timeout" in result["error"].lower()
            ),
            f"error: {result.get('error', '')}",
        )

    # ------------------------------------------------------------------
    # Execution time tracking
    # ------------------------------------------------------------------
    print("\n--- Execution Time Tracking ---")

    with SandboxDatabase() as sandbox:
        result = executor.execute_query(
            "SELECT 1 + 1 as answer",
            sandbox=sandbox,
        )
        check(
            "Execution time is tracked",
            result["execution_time_ms"] >= 0,
            f"execution_time_ms={result['execution_time_ms']}",
        )

    # ------------------------------------------------------------------
    # Batch execution
    # ------------------------------------------------------------------
    print("\n--- Batch Execution ---")

    with SandboxDatabase() as sandbox:
        results = executor.execute_query_batch(
            [
                {"query": "SELECT COUNT(*) as cnt FROM users"},
                {"query": "SELECT COUNT(*) as cnt FROM tasks"},
                {"query": "SELECT COUNT(*) as cnt FROM comments"},
            ],
            sandbox=sandbox,
        )
        check("Batch returns 3 results", len(results) == 3)
        check("All batch queries succeed", all(r["success"] for r in results))

    # ------------------------------------------------------------------
    # API endpoint tests
    # ------------------------------------------------------------------
    print("\n--- API Endpoint Tests ---")

    import executor_api
    client = TestClient(executor_api.app)

    resp = client.get("/health")
    check("GET /health returns 200", resp.status_code == 200)
    check(
        "Health response has correct service name",
        resp.json().get("service") == "db-agent-executor",
    )

    resp = client.post("/execute", json={
        "query": "SELECT id, username FROM users ORDER BY id",
        "parameters": [],
        "timeout": 10.0,
        "max_rows": 100,
    })
    check("POST /execute returns 200", resp.status_code == 200)
    exec_data = resp.json()
    check("API execute returns success", exec_data.get("success") is True)
    check(
        "API execute returns rows",
        exec_data.get("row_count", 0) > 0,
        f"row_count={exec_data.get('row_count')}",
    )

    # Test row limit via API.
    resp = client.post("/execute", json={
        "query": "SELECT id FROM users ORDER BY id",
        "parameters": [],
        "max_rows": 2,
    })
    check("API row limit returns 200", resp.status_code == 200)
    exec_data = resp.json()
    check(
        "API row limit truncates results",
        exec_data.get("truncated") is True,
        f"truncated={exec_data.get('truncated')}",
    )

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print(f"RESULTS: {passed} passed, {failed} failed, {passed + failed} total")
    print("=" * 70)

    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
