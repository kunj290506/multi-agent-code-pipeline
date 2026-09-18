"""
DB Agent -- Test Script.

Validates the query-generation and safety-validation logic with
multiple example inputs. Tests both offline mode and the validation
rules. The full Ollama integration test is skipped if the server
is not reachable.

Run with:
    python test_db_agent.py
"""

import json
import os
import sys

# Ensure imports resolve from the db-agent directory.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402
import query_generator  # noqa: E402


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

OFFLINE_TEST_CASES = [
    {
        "input": "List all users in the system",
        "expected_type": "SELECT",
        "expect_safe": True,
    },
    {
        "input": "Create a new user named Alice with email alice@example.com",
        "expected_type": "INSERT",
        "expect_safe": True,
    },
    {
        "input": "Show all tasks assigned to user John",
        "expected_type": "SELECT",
        "expect_safe": True,
    },
    {
        "input": "Get all high priority and critical tasks",
        "expected_type": "SELECT",
        "expect_safe": True,
    },
]

SAFETY_TEST_CASES = [
    {
        "query": "SELECT * FROM users WHERE id = 1",
        "expect_safe": True,
        "description": "Simple SELECT with WHERE clause",
    },
    {
        "query": "INSERT INTO users (username, email) VALUES ('test', 'test@test.com')",
        "expect_safe": True,
        "description": "Simple INSERT",
    },
    {
        "query": "DELETE FROM users;",
        "expect_safe": False,
        "description": "Unscoped DELETE (no WHERE)",
    },
    {
        "query": "DROP TABLE users;",
        "expect_safe": False,
        "description": "DROP TABLE",
    },
    {
        "query": "TRUNCATE TABLE users;",
        "expect_safe": False,
        "description": "TRUNCATE",
    },
    {
        "query": "DELETE FROM users WHERE id = 5",
        "expect_safe": True,
        "description": "Scoped DELETE with WHERE clause",
    },
    {
        "query": "SELECT * FROM users; DROP TABLE users;",
        "expect_safe": False,
        "description": "Statement chaining (injection attempt)",
    },
    {
        "query": "SELECT * FROM users -- admin bypass",
        "expect_safe": False,
        "description": "Comment injection",
    },
    {
        "query": "ALTER TABLE users ADD COLUMN admin BOOLEAN",
        "expect_safe": False,
        "description": "ALTER TABLE",
    },
    {
        "query": "GRANT ALL PRIVILEGES ON users TO public",
        "expect_safe": False,
        "description": "GRANT statement",
    },
    {
        "query": "UPDATE users SET role = 'admin' WHERE id = 1",
        "expect_safe": True,
        "description": "Scoped UPDATE with WHERE clause",
    },
]


def _separator(title: str) -> None:
    print()
    print("=" * 60)
    print(f"  {title}")
    print("=" * 60)


def test_offline_generation() -> bool:
    """Test offline query generation for each example."""
    _separator("Test: Offline Query Generation")
    all_passed = True

    for i, case in enumerate(OFFLINE_TEST_CASES):
        result = query_generator.generate_query_offline(case["input"])

        has_query = bool(result.get("query"))
        type_match = result.get("query_type") == case["expected_type"]
        is_safe = result.get("safety_check", {}).get("passed", False)

        passed = has_query and type_match and (is_safe == case["expect_safe"])
        status = "PASS" if passed else "FAIL"

        print(f"  Case {i+1}: {case['input'][:50]}...")
        print(f"    Query: {result['query'][:60]}...")
        print(f"    Type: {result['query_type']} (expected: {case['expected_type']})")
        print(f"    Safe: {is_safe} (expected: {case['expect_safe']})")
        print(f"    [{status}]")

        if not passed:
            all_passed = False

    return all_passed


def test_safety_validation() -> bool:
    """Test the safety validation rules against known queries."""
    _separator("Test: Safety Validation")
    all_passed = True

    for i, case in enumerate(SAFETY_TEST_CASES):
        violations = query_generator.validate_query(case["query"])
        is_safe = len(violations) == 0

        passed = is_safe == case["expect_safe"]
        status = "PASS" if passed else "FAIL"

        print(f"  Case {i+1}: {case['description']}")
        print(f"    Query: {case['query'][:60]}...")
        print(f"    Safe: {is_safe} (expected: {case['expect_safe']})")
        if violations:
            for v in violations:
                print(f"    Violation: {v[:70]}...")
        print(f"    [{status}]")

        if not passed:
            all_passed = False

    return all_passed


def test_json_extraction() -> bool:
    """Test JSON extraction from various model output formats."""
    _separator("Test: JSON Extraction")
    all_passed = True

    test_cases = [
        (
            '{"query": "SELECT 1", "parameters": [], "query_type": "SELECT", '
            '"explanation": "test"}',
            True,
        ),
        (
            '```json\n{"query": "SELECT 1", "parameters": [], '
            '"query_type": "SELECT", "explanation": "test"}\n```',
            True,
        ),
        (
            "No JSON here at all",
            False,
        ),
    ]

    for i, (text, should_succeed) in enumerate(test_cases):
        try:
            query_generator._extract_json(text)
            if should_succeed:
                print(f"  Case {i+1}: [PASS] Extracted successfully.")
            else:
                print(f"  Case {i+1}: [FAIL] Should have raised an error.")
                all_passed = False
        except (ValueError, json.JSONDecodeError):
            if not should_succeed:
                print(f"  Case {i+1}: [PASS] Correctly rejected.")
            else:
                print(f"  Case {i+1}: [FAIL] Should have extracted JSON.")
                all_passed = False

    return all_passed


def test_response_validation() -> bool:
    """Test structural validation of LLM responses."""
    _separator("Test: Response Validation")
    all_passed = True

    # Valid response
    valid = {
        "query": "SELECT * FROM users",
        "parameters": [],
        "query_type": "SELECT",
        "explanation": "Gets all users.",
    }
    errors = query_generator._validate_response(valid)
    if errors:
        print(f"  Valid response: [FAIL] Errors: {errors}")
        all_passed = False
    else:
        print("  Valid response: [PASS]")

    # Missing query
    bad1 = {"parameters": [], "query_type": "SELECT", "explanation": "test"}
    errors = query_generator._validate_response(bad1)
    if errors:
        print("  Missing query: [PASS]")
    else:
        print("  Missing query: [FAIL]")
        all_passed = False

    # Invalid query_type
    bad2 = {
        "query": "SELECT 1",
        "parameters": [],
        "query_type": "MERGE",
        "explanation": "test",
    }
    errors = query_generator._validate_response(bad2)
    if errors:
        print("  Invalid query_type: [PASS]")
    else:
        print("  Invalid query_type: [FAIL]")
        all_passed = False

    return all_passed


def test_ollama_integration() -> bool:
    """Test full query generation with Ollama (requires running server)."""
    _separator("Test: Ollama Integration (requires running server)")
    try:
        import requests
        response = requests.get(f"{config.OLLAMA_BASE_URL}/api/tags", timeout=3)
        response.raise_for_status()
    except Exception:
        print("  [SKIP] Ollama server is not reachable.")
        return True

    test_requests = [
        "List all users who signed up this month",
        "Find tasks with high priority that are not yet completed",
    ]

    all_passed = True
    for nl_request in test_requests:
        try:
            result = query_generator.generate_query(nl_request)
            print(f"  Request: {nl_request}")
            print(f"  Query: {result['query'][:60]}...")
            print(f"  Type: {result['query_type']}")
            print(f"  Safe: {result['safety_check']['passed']}")
            print("  [PASS]")
        except requests.RequestException as exc:
            print(f"  [SKIP] Ollama generation endpoint is unavailable: {exc}")
            return True
        except ValueError as exc:
            print(f"  Request: {nl_request}")
            print(f"  [FAIL] {exc}")
            all_passed = False

    return all_passed


def main() -> None:
    results = {}

    results["offline_generation"] = test_offline_generation()
    results["safety_validation"] = test_safety_validation()
    results["json_extraction"] = test_json_extraction()
    results["response_validation"] = test_response_validation()
    results["ollama_integration"] = test_ollama_integration()

    _separator("Summary")
    all_passed = True
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {name}: [{status}]")
        if not passed:
            all_passed = False

    print()
    if all_passed:
        print("All tests passed.")
    else:
        print("Some tests failed. Review output above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
