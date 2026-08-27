"""
DB Agent -- Query Generation Module.

Converts natural-language requests into safe, parameterized SQL queries.
This module handles ONLY query generation -- query execution and sandboxing
are handled by a separate component (out of scope here).

Key features:
- Uses the local Ollama model for NL-to-SQL translation.
- Validates generated queries against a safety ruleset.
- Rejects dangerous operations (unscoped DELETE, DROP, TRUNCATE, etc.).
- Returns parameterized queries to prevent SQL injection.
"""

import json
import re

import requests

import config


# ---------------------------------------------------------------------------
# Safety rules
# ---------------------------------------------------------------------------

# SQL keywords that are unconditionally blocked.
BLOCKED_KEYWORDS: list[str] = [
    "DROP TABLE",
    "DROP DATABASE",
    "DROP INDEX",
    "DROP VIEW",
    "TRUNCATE",
    "ALTER TABLE",
    "GRANT",
    "REVOKE",
    "EXEC",
    "EXECUTE",
    "xp_",
    "sp_",
]

# Patterns that indicate an unscoped destructive operation.
UNSAFE_PATTERNS: list[re.Pattern] = [
    # DELETE without WHERE clause
    re.compile(
        r"\bDELETE\s+FROM\s+\w+\s*;",
        re.IGNORECASE,
    ),
    # UPDATE without WHERE clause
    re.compile(
        r"\bUPDATE\s+\w+\s+SET\s+.*?;\s*$",
        re.IGNORECASE | re.DOTALL,
    ),
    # Multiple statements (statement chaining via semicolon)
    re.compile(r";\s*\b(SELECT|INSERT|UPDATE|DELETE|DROP|ALTER)\b", re.IGNORECASE),
    # Comment injection
    re.compile(r"(--|/\*|\*/)", re.IGNORECASE),
]


def validate_query(sql: str) -> list[str]:
    """Check a SQL query against safety rules.

    Returns a list of violation descriptions. An empty list means the
    query is considered safe.
    """
    violations: list[str] = []
    upper_sql = sql.upper()

    # Check blocked keywords.
    for keyword in BLOCKED_KEYWORDS:
        if keyword.upper() in upper_sql:
            violations.append(
                f"Blocked keyword detected: '{keyword}'. "
                f"This operation is not permitted."
            )

    # Check unsafe patterns.
    for pattern in UNSAFE_PATTERNS:
        if pattern.search(sql):
            violations.append(
                f"Unsafe pattern detected: {pattern.pattern}. "
                f"Destructive operations must include a WHERE clause."
            )

    return violations


# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a SQL query generator. Given a database schema and a natural-language
request, generate a safe, correct SQL query.

Rules:
1. Output ONLY valid JSON -- no markdown fences, no commentary.
2. Use the exact output schema shown below.
3. Use parameterized queries with ? placeholders for user-supplied values.
4. List the parameter values in the "parameters" array in the correct order.
5. Never generate DROP, TRUNCATE, ALTER, or other DDL statements.
6. DELETE and UPDATE statements MUST include a WHERE clause.
7. Use standard SQL syntax compatible with SQLite.
8. If the request is ambiguous, make reasonable assumptions and note them.

Output schema:
{
  "query": "SELECT ... FROM ... WHERE ... = ?",
  "parameters": ["value1"],
  "query_type": "SELECT|INSERT|UPDATE|DELETE",
  "explanation": "Brief explanation of what this query does",
  "assumptions": ["Any assumptions made about the request"]
}"""


def _build_prompt(nl_request: str, schema: str) -> str:
    """Build the full prompt for the Ollama model."""
    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"Database schema:\n{schema}\n\n"
        f"Request: {nl_request}\n\n"
        f"Respond with the JSON output:"
    )


def _extract_json(text: str) -> dict:
    """Extract a JSON object from model output, tolerating markdown fences."""
    cleaned = re.sub(r"```(?:json)?\s*", "", text)
    cleaned = cleaned.strip()

    brace_start = cleaned.find("{")
    if brace_start == -1:
        raise ValueError("No JSON object found in model output.")

    depth = 0
    for i in range(brace_start, len(cleaned)):
        if cleaned[i] == "{":
            depth += 1
        elif cleaned[i] == "}":
            depth -= 1
            if depth == 0:
                json_str = cleaned[brace_start : i + 1]
                return json.loads(json_str)

    raise ValueError("Unbalanced braces in model output.")


def _validate_response(response: dict) -> list[str]:
    """Validate the structure of the LLM response."""
    errors: list[str] = []

    if "query" not in response or not response["query"].strip():
        errors.append("Missing or empty 'query' field.")

    if "parameters" not in response:
        errors.append("Missing 'parameters' field.")
    elif not isinstance(response["parameters"], list):
        errors.append("'parameters' must be a list.")

    valid_types = {"SELECT", "INSERT", "UPDATE", "DELETE"}
    query_type = response.get("query_type", "").upper()
    if query_type not in valid_types:
        errors.append(
            f"Invalid 'query_type': '{query_type}'. Must be one of {valid_types}."
        )

    return errors


def generate_query(
    nl_request: str,
    schema: str | None = None,
    max_retries: int = 2,
) -> dict:
    """Convert a natural-language request into a SQL query.

    Args:
        nl_request: Plain-language description of the desired data operation.
        schema: The database schema to generate queries against.
                Defaults to the placeholder schema in config.
        max_retries: Number of additional LLM attempts if output is invalid.

    Returns:
        A dict with keys: query, parameters, query_type, explanation,
        assumptions, safety_check.

    Raises:
        ValueError: If the model fails to produce valid output, or if
                    the generated query fails safety validation.
    """
    schema = schema or config.PLACEHOLDER_SCHEMA
    prompt = _build_prompt(nl_request, schema)

    last_error = ""
    for attempt in range(1 + max_retries):
        if attempt > 0:
            prompt_with_correction = (
                f"{prompt}\n\n"
                f"Your previous response had errors: {last_error}\n"
                f"Please fix the errors and respond with valid JSON only."
            )
        else:
            prompt_with_correction = prompt

        payload = {
            "model": config.OLLAMA_MODEL,
            "prompt": prompt_with_correction,
            "stream": False,
            "options": {
                "temperature": config.TEMPERATURE,
                "num_predict": config.MAX_TOKENS,
            },
        }

        response = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/generate",
            json=payload,
            timeout=120,
        )
        response.raise_for_status()
        raw_output = response.json().get("response", "")

        try:
            result = _extract_json(raw_output)
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = f"JSON parsing failed: {exc}"
            continue

        struct_errors = _validate_response(result)
        if struct_errors:
            last_error = "; ".join(struct_errors)
            continue

        # Safety check on the generated SQL.
        safety_violations = validate_query(result["query"])
        result["safety_check"] = {
            "passed": len(safety_violations) == 0,
            "violations": safety_violations,
        }

        if safety_violations:
            raise ValueError(
                f"Generated query failed safety check: "
                f"{'; '.join(safety_violations)}"
            )

        return result

    raise ValueError(
        f"Failed to generate a valid query after {1 + max_retries} attempts. "
        f"Last error: {last_error}"
    )


def generate_query_offline(nl_request: str) -> dict:
    """Return a deterministic query result without calling the LLM.

    Useful for testing validation and downstream processing.
    """
    # Simple keyword-based matching for offline mode.
    lower = nl_request.lower()

    if "all users" in lower or "list users" in lower:
        return {
            "query": "SELECT id, username, email, role, created_at FROM users",
            "parameters": [],
            "query_type": "SELECT",
            "explanation": "Retrieves all user records from the users table.",
            "assumptions": [],
            "safety_check": {"passed": True, "violations": []},
        }
    elif "create" in lower and "user" in lower:
        return {
            "query": (
                "INSERT INTO users (username, email, role) VALUES (?, ?, ?)"
            ),
            "parameters": ["placeholder_user", "user@example.com", "member"],
            "query_type": "INSERT",
            "explanation": "Inserts a new user record into the users table.",
            "assumptions": ["Default role is 'member'."],
            "safety_check": {"passed": True, "violations": []},
        }
    elif "tasks" in lower and ("assigned" in lower or "user" in lower):
        return {
            "query": (
                "SELECT t.id, t.title, t.status, t.priority, u.username "
                "FROM tasks t "
                "JOIN users u ON t.assigned_to = u.id "
                "WHERE u.username = ?"
            ),
            "parameters": ["placeholder_user"],
            "query_type": "SELECT",
            "explanation": "Retrieves all tasks assigned to a specific user.",
            "assumptions": ["Filtering by username."],
            "safety_check": {"passed": True, "violations": []},
        }
    elif "high priority" in lower or "critical" in lower:
        return {
            "query": (
                "SELECT id, title, status, assigned_to "
                "FROM tasks "
                "WHERE priority IN (?, ?) "
                "ORDER BY created_at DESC"
            ),
            "parameters": ["high", "critical"],
            "query_type": "SELECT",
            "explanation": "Retrieves high and critical priority tasks.",
            "assumptions": [],
            "safety_check": {"passed": True, "violations": []},
        }
    else:
        return {
            "query": "SELECT * FROM tasks WHERE status = ?",
            "parameters": ["pending"],
            "query_type": "SELECT",
            "explanation": (
                f"Fallback: lists pending tasks. "
                f"Original request: {nl_request}"
            ),
            "assumptions": [
                "Could not precisely map the request. Defaulting to pending tasks."
            ],
            "safety_check": {"passed": True, "violations": []},
        }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate SQL from a natural-language request."
    )
    parser.add_argument("request", help="Natural-language data request.")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Use offline mode (no Ollama required).",
    )
    args = parser.parse_args()

    if args.offline:
        result = generate_query_offline(args.request)
    else:
        result = generate_query(args.request)

    print(json.dumps(result, indent=2))
