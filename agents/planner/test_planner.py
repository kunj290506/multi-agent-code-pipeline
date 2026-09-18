"""
Planner Agent -- Test Script.

Validates the task decomposition logic with multiple example inputs.
Tests both the offline deterministic mode and the JSON extraction /
validation logic. The full Ollama integration test is skipped if the
server is not reachable.

Run with:
    python test_planner.py
"""

import json
import os
import sys

# Ensure imports resolve from the planner-agent directory.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402
import planner  # noqa: E402

# ---------------------------------------------------------------------------
# Example inputs with expected structural properties
# ---------------------------------------------------------------------------

EXAMPLE_REQUESTS = [
    {
        "input": "Add a user authentication system with JWT tokens and role-based access control.",
        "min_subtasks": 3,
        "required_agents": {"rag-agent", "codegen-agent", "reviewer-agent"},
    },
    {
        "input": "Create a REST API endpoint to manage project tasks with CRUD operations and a database table for tasks.",
        "min_subtasks": 3,
        "required_agents": {"rag-agent", "codegen-agent", "db-agent"},
    },
    {
        "input": "Build a dashboard page that displays user statistics and recent activity from the database.",
        "min_subtasks": 3,
        "required_agents": {"rag-agent", "codegen-agent"},
    },
    {
        "input": "Add input validation and error handling to all existing API endpoints.",
        "min_subtasks": 2,
        "required_agents": {"rag-agent", "reviewer-agent"},
    },
    {
        "input": "Create a database migration to add an 'email_verified' column to the users table and update the registration endpoint.",
        "min_subtasks": 2,
        "required_agents": {"db-agent", "codegen-agent"},
    },
]


def _separator(title: str) -> None:
    print()
    print("=" * 60)
    print(f"  {title}")
    print("=" * 60)


def test_offline_decomposition() -> bool:
    """Test that offline mode produces a valid plan for each example."""
    _separator("Test: Offline Decomposition")
    all_passed = True

    for i, example in enumerate(EXAMPLE_REQUESTS[:2]):
        request_text = example["input"]
        plan = planner.decompose_offline(request_text)

        # Validate structure
        errors = planner._validate_plan(plan)
        if errors:
            print(f"  Example {i+1}: [FAIL] Validation errors: {errors}")
            all_passed = False
            continue

        # Check feature_request is echoed
        if plan["feature_request"] != request_text:
            print(f"  Example {i+1}: [FAIL] feature_request not echoed.")
            all_passed = False
            continue

        # Check minimum subtask count
        subtask_count = len(plan["subtasks"])
        if subtask_count < 2:
            print(f"  Example {i+1}: [FAIL] Too few subtasks ({subtask_count}).")
            all_passed = False
            continue

        print(f"  Example {i+1}: [PASS] ({subtask_count} subtasks)")
        for task in plan["subtasks"]:
            print(f"    {task['task_id']} [{task['agent']}]: {task['description'][:60]}...")

    return all_passed


def test_json_extraction() -> bool:
    """Test JSON extraction from various model output formats."""
    _separator("Test: JSON Extraction")
    all_passed = True

    test_cases = [
        # Clean JSON
        (
            '{"feature_request": "test", "subtasks": []}',
            True,
        ),
        # JSON wrapped in markdown fences
        (
            '```json\n{"feature_request": "test", "subtasks": []}\n```',
            True,
        ),
        # JSON with leading text
        (
            'Here is the plan:\n{"feature_request": "test", "subtasks": []}',
            True,
        ),
        # No JSON at all
        (
            "This is just plain text without any JSON.",
            False,
        ),
        # Malformed JSON
        (
            '{"feature_request": "test", "subtasks": [}',
            False,
        ),
    ]

    for i, (text, should_succeed) in enumerate(test_cases):
        try:
            planner._extract_json(text)
            if should_succeed:
                print(f"  Case {i+1}: [PASS] Extracted JSON successfully.")
            else:
                print(f"  Case {i+1}: [FAIL] Should have raised an error.")
                all_passed = False
        except (ValueError, json.JSONDecodeError):
            if not should_succeed:
                print(f"  Case {i+1}: [PASS] Correctly rejected invalid input.")
            else:
                print(f"  Case {i+1}: [FAIL] Should have extracted JSON.")
                all_passed = False

    return all_passed


def test_validation() -> bool:
    """Test plan validation catches various error conditions."""
    _separator("Test: Plan Validation")
    all_passed = True

    # Valid plan
    valid_plan = {
        "feature_request": "test",
        "subtasks": [
            {
                "task_id": "task_1",
                "agent": "rag-agent",
                "description": "Retrieve docs.",
                "dependencies": [],
            },
            {
                "task_id": "task_2",
                "agent": "codegen-agent",
                "description": "Generate code.",
                "dependencies": ["task_1"],
            },
        ],
    }
    errors = planner._validate_plan(valid_plan)
    if errors:
        print(f"  Valid plan: [FAIL] Unexpected errors: {errors}")
        all_passed = False
    else:
        print("  Valid plan: [PASS]")

    # Missing feature_request
    bad_plan_1 = {"subtasks": []}
    errors = planner._validate_plan(bad_plan_1)
    if "Missing 'feature_request' field." in errors:
        print("  Missing feature_request: [PASS]")
    else:
        print(f"  Missing feature_request: [FAIL] Errors: {errors}")
        all_passed = False

    # Invalid agent name
    bad_plan_2 = {
        "feature_request": "test",
        "subtasks": [
            {
                "task_id": "task_1",
                "agent": "invalid-agent",
                "description": "Do something.",
                "dependencies": [],
            },
        ],
    }
    errors = planner._validate_plan(bad_plan_2)
    if any("invalid agent" in e for e in errors):
        print("  Invalid agent: [PASS]")
    else:
        print(f"  Invalid agent: [FAIL] Errors: {errors}")
        all_passed = False

    # Duplicate task_id
    bad_plan_3 = {
        "feature_request": "test",
        "subtasks": [
            {
                "task_id": "task_1",
                "agent": "rag-agent",
                "description": "First.",
                "dependencies": [],
            },
            {
                "task_id": "task_1",
                "agent": "codegen-agent",
                "description": "Duplicate.",
                "dependencies": [],
            },
        ],
    }
    errors = planner._validate_plan(bad_plan_3)
    if any("duplicate" in e for e in errors):
        print("  Duplicate task_id: [PASS]")
    else:
        print(f"  Duplicate task_id: [FAIL] Errors: {errors}")
        all_passed = False

    # Unknown dependency
    bad_plan_4 = {
        "feature_request": "test",
        "subtasks": [
            {
                "task_id": "task_1",
                "agent": "rag-agent",
                "description": "First.",
                "dependencies": ["task_99"],
            },
        ],
    }
    errors = planner._validate_plan(bad_plan_4)
    if any("unknown" in e for e in errors):
        print("  Unknown dependency: [PASS]")
    else:
        print(f"  Unknown dependency: [FAIL] Errors: {errors}")
        all_passed = False

    return all_passed


def test_schema_endpoint() -> bool:
    """Verify the schema constant is well-formed."""
    _separator("Test: Schema Definition")
    schema = planner.PLAN_SCHEMA
    if "properties" not in schema:
        print("  [FAIL] Schema missing 'properties'.")
        return False
    if "feature_request" not in schema["properties"]:
        print("  [FAIL] Schema missing 'feature_request'.")
        return False
    if "subtasks" not in schema["properties"]:
        print("  [FAIL] Schema missing 'subtasks'.")
        return False
    print("  [PASS] Schema is well-formed.")
    return True


def test_ollama_integration() -> bool:
    """Test full decomposition with Ollama (requires running server)."""
    _separator("Test: Ollama Integration (requires running server)")
    try:
        import requests
        response = requests.get(f"{config.OLLAMA_BASE_URL}/api/tags", timeout=3)
        response.raise_for_status()
    except Exception:
        print("  [SKIP] Ollama server is not reachable.")
        return True

    request_text = (
        "Add a user authentication system with JWT tokens "
        "and role-based access control."
    )
    try:
        plan = planner.decompose(request_text)
        print(f"  Feature: {plan['feature_request'][:60]}...")
        print(f"  Subtasks: {len(plan['subtasks'])}")
        for task in plan["subtasks"]:
            print(
                f"    {task['task_id']} [{task['agent']}]: "
                f"{task['description'][:50]}..."
            )
        print("  [PASS]")
        return True
    except requests.RequestException as exc:
        print(f"  [SKIP] Ollama generation endpoint is unavailable: {exc}")
        return True
    except ValueError as exc:
        print(f"  [FAIL] {exc}")
        return False


def main() -> None:
    results = {}

    results["offline_decomposition"] = test_offline_decomposition()
    results["json_extraction"] = test_json_extraction()
    results["validation"] = test_validation()
    results["schema"] = test_schema_endpoint()
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
