"""
Test script for the Reviewer / QA Agent.

Covers code samples that should pass and samples with known violations,
with clear expected outcomes for each.
"""

import json
import os
import sys

# Ensure the reviewer-agent directory is on the Python path.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient

import reviewer


# ---------------------------------------------------------------------------
# Test code samples
# ---------------------------------------------------------------------------

# A well-written Python module that should pass all checks.
CLEAN_CODE = '''\
"""
Utility module for greeting operations.

Provides functions to generate greeting messages.
"""


def greet(name: str) -> str:
    """Return a greeting message for the given name.

    Args:
        name: The name of the person to greet.

    Returns:
        A greeting string.
    """
    return f"Hello, {name}!"


def farewell(name: str) -> str:
    """Return a farewell message for the given name.

    Args:
        name: The name of the person to bid farewell.

    Returns:
        A farewell string.
    """
    return f"Goodbye, {name}!"
'''

# Code with a syntax error.
SYNTAX_ERROR_CODE = '''\
def broken_function(
    print("missing closing paren"
'''

# Code with security issues.
SECURITY_ISSUES_CODE = '''\
"""Module with security issues for testing."""

import os
import subprocess
import pickle


def dangerous_eval(user_input):
    """Evaluate user input (dangerous)."""
    return eval(user_input)


def run_command(cmd):
    """Run a system command."""
    os.system(cmd)
    return subprocess.call(cmd, shell=True)


def load_data(data):
    """Load pickled data."""
    return pickle.loads(data)


API_KEY = "sk-secret-key-12345"
'''

# Code with style issues.
STYLE_ISSUES_CODE = '''\
"""Module with style issues."""


def BadFunctionName():
    """A function with PascalCase name instead of snake_case."""
    return True


class badly_named_class:
    """A class with snake_case name instead of PascalCase."""
    pass
'''

# Code missing required elements.
MISSING_ELEMENTS_CODE = '''\
def process(data):
    return data * 2


def transform(x, y):
    result = x + y
    return result
'''

# Non-Python code (should skip most checks).
JAVASCRIPT_CODE = '''\
function greet(name) {
    return `Hello, ${name}!`;
}

module.exports = { greet };
'''


def run_tests():
    """Run all reviewer agent tests and report results."""
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
    print("REVIEWER / QA AGENT -- TEST SUITE")
    print("=" * 70)

    # ------------------------------------------------------------------
    # Clean code should pass
    # ------------------------------------------------------------------
    print("\n--- Clean Code (Should Pass) ---")
    result = reviewer.review_code(CLEAN_CODE)
    check(
        "Clean code verdict is 'pass'",
        result["verdict"] == "pass",
        f"got '{result['verdict']}'",
    )
    error_count = result["issues_by_severity"].get("error", 0)
    critical_count = result["issues_by_severity"].get("critical", 0)
    check(
        "Clean code has no errors or critical issues",
        error_count == 0 and critical_count == 0,
        f"errors={error_count}, critical={critical_count}",
    )

    # ------------------------------------------------------------------
    # Syntax error should fail
    # ------------------------------------------------------------------
    print("\n--- Syntax Error Code (Should Fail) ---")
    result = reviewer.review_code(SYNTAX_ERROR_CODE)
    check(
        "Syntax error verdict is 'fail'",
        result["verdict"] == "fail",
        f"got '{result['verdict']}'",
    )
    syn_issues = [i for i in result["issues"] if i["category"] == "syntax"]
    check(
        "Syntax error is detected",
        len(syn_issues) > 0,
        f"found {len(syn_issues)} syntax issues",
    )
    check(
        "Syntax issue has rule_id SYN001",
        any(i["rule_id"] == "SYN001" for i in syn_issues),
    )
    check(
        "Syntax issue severity is critical",
        all(i["severity"] == "critical" for i in syn_issues),
    )

    # ------------------------------------------------------------------
    # Security issues should be detected
    # ------------------------------------------------------------------
    print("\n--- Security Issues Code (Should Fail) ---")
    result = reviewer.review_code(SECURITY_ISSUES_CODE)
    check(
        "Security issues verdict is 'fail'",
        result["verdict"] == "fail",
        f"got '{result['verdict']}'",
    )

    sec_issues = [i for i in result["issues"] if i["category"] == "security"]
    check(
        "Security issues detected",
        len(sec_issues) >= 4,
        f"found {len(sec_issues)} security issues",
    )

    # Check for specific rules.
    sec_rule_ids = {i["rule_id"] for i in sec_issues}
    check("SEC001 (eval) detected", "SEC001" in sec_rule_ids)
    check("SEC003 (subprocess) detected", "SEC003" in sec_rule_ids)
    check("SEC005 (hardcoded secret) detected", "SEC005" in sec_rule_ids)
    check("SEC006 (os.system) detected", "SEC006" in sec_rule_ids)
    check("SEC007 (pickle) detected", "SEC007" in sec_rule_ids)

    # ------------------------------------------------------------------
    # Style issues should be detected
    # ------------------------------------------------------------------
    print("\n--- Style Issues Code ---")
    result = reviewer.review_code(STYLE_ISSUES_CODE)
    style_issues = [i for i in result["issues"] if i["category"] == "style"]
    check(
        "Style issues detected",
        len(style_issues) >= 2,
        f"found {len(style_issues)} style issues",
    )

    style_rule_ids = {i["rule_id"] for i in style_issues}
    check("STY003 (function naming) detected", "STY003" in style_rule_ids)
    check("STY004 (class naming) detected", "STY004" in style_rule_ids)

    # ------------------------------------------------------------------
    # Missing elements should be detected
    # ------------------------------------------------------------------
    print("\n--- Missing Elements Code ---")
    result = reviewer.review_code(MISSING_ELEMENTS_CODE)
    req_issues = [
        i for i in result["issues"]
        if i["category"] == "required_elements"
    ]
    check(
        "Missing elements detected",
        len(req_issues) >= 2,
        f"found {len(req_issues)} required-element issues",
    )

    req_rule_ids = {i["rule_id"] for i in req_issues}
    check("REQ001 (module docstring) detected", "REQ001" in req_rule_ids)
    check("REQ002 (function docstring) detected", "REQ002" in req_rule_ids)
    check("REQ003 (type hints) detected", "REQ003" in req_rule_ids)

    # ------------------------------------------------------------------
    # Category filtering
    # ------------------------------------------------------------------
    print("\n--- Category Filtering ---")
    result = reviewer.review_code(
        SECURITY_ISSUES_CODE, categories=["syntax"]
    )
    check(
        "Filtering to 'syntax' only runs syntax checks",
        result["categories_checked"] == ["syntax"],
    )
    non_syntax = [
        i for i in result["issues"] if i["category"] != "syntax"
    ]
    check(
        "No non-syntax issues when filtering to syntax only",
        len(non_syntax) == 0,
    )

    # ------------------------------------------------------------------
    # Non-Python code
    # ------------------------------------------------------------------
    print("\n--- Non-Python Code ---")
    result = reviewer.review_code(JAVASCRIPT_CODE, language="javascript")
    check(
        "JavaScript code produces no Python-specific issues",
        result["total_issues"] == 0,
        f"got {result['total_issues']} issues",
    )
    check(
        "JavaScript code verdict is 'pass'",
        result["verdict"] == "pass",
    )

    # ------------------------------------------------------------------
    # Output format validation
    # ------------------------------------------------------------------
    print("\n--- Output Format ---")
    result = reviewer.review_code(CLEAN_CODE)
    required_keys = [
        "verdict", "summary", "total_issues",
        "issues_by_severity", "issues", "categories_checked",
    ]
    all_present = all(k in result for k in required_keys)
    check("All required keys present in output", all_present)

    # JSON serialization round-trip.
    json_str = json.dumps(result)
    round_trip = json.loads(json_str)
    check("JSON round-trip succeeds", round_trip == result)

    # ------------------------------------------------------------------
    # API endpoint tests
    # ------------------------------------------------------------------
    print("\n--- API Endpoint Tests ---")

    import api
    client = TestClient(api.app)

    resp = client.get("/health")
    check("GET /health returns 200", resp.status_code == 200)
    check(
        "Health response has correct service name",
        resp.json().get("service") == "reviewer-agent",
    )

    resp = client.get("/rules")
    check("GET /rules returns 200", resp.status_code == 200)
    rules_data = resp.json()
    check(
        "Rules response has rule categories",
        "syntax" in rules_data.get("rules", {}),
    )

    # Review via API.
    resp = client.post("/review", json={
        "code": CLEAN_CODE,
        "language": "python",
    })
    check("POST /review (clean code) returns 200", resp.status_code == 200)
    check(
        "API review verdict is 'pass' for clean code",
        resp.json().get("verdict") == "pass",
    )

    resp = client.post("/review", json={
        "code": SECURITY_ISSUES_CODE,
        "language": "python",
        "categories": ["security"],
    })
    check("POST /review (security) returns 200", resp.status_code == 200)
    check(
        "API review verdict is 'fail' for security issues",
        resp.json().get("verdict") == "fail",
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
