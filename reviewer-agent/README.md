# Reviewer / QA Agent

## Purpose

The Reviewer / QA Agent takes generated code as input and checks it against
a defined rule set. It produces a structured **pass/fail verdict** with a
detailed list of specific issues found, all in JSON format.

This agent is designed to be called by the n8n orchestration workflow after
the Code-Gen Agent produces an artifact, providing an automated quality gate
before code is accepted.

---

## Rule Set

### Syntax Validity (`syntax`)

| Rule ID | Description                                    | Severity |
|---------|------------------------------------------------|----------|
| SYN001  | Code fails to parse (syntax error detected)    | critical |

### Required Elements (`required_elements`)

| Rule ID | Description                                    | Severity |
|---------|------------------------------------------------|----------|
| REQ001  | Missing module-level docstring                 | warning  |
| REQ002  | Missing function/method docstring              | warning  |
| REQ003  | Missing type hint on function argument         | info     |

### Security (`security`)

| Rule ID | Description                                    | Severity |
|---------|------------------------------------------------|----------|
| SEC001  | Use of `eval()`                                | error    |
| SEC002  | Use of `exec()`                                | error    |
| SEC003  | Direct subprocess invocation                   | error    |
| SEC004  | Dynamic import via `__import__()`              | error    |
| SEC005  | Hardcoded secret or credential                 | error    |
| SEC006  | Use of `os.system()`                           | error    |
| SEC007  | Use of `pickle` with untrusted data            | error    |

### Style Conventions (`style`)

| Rule ID | Description                                    | Severity |
|---------|------------------------------------------------|----------|
| STY001  | Line exceeds maximum length (default: 120)     | info     |
| STY002  | Trailing whitespace                            | info     |
| STY003  | Function name not in snake_case                | warning  |
| STY004  | Class name not in PascalCase                   | warning  |

---

## Verdict Logic

The verdict is determined by the **fail threshold** (configurable, default: `error`):

- If any issue has severity **at or above** the threshold, the verdict is `fail`.
- Otherwise, the verdict is `pass`.

Severity ordering: `info` < `warning` < `error` < `critical`.

---

## Input / Output Schemas

### Input (POST /review)

```json
{
  "code": "def hello():\n    return 'world'",
  "language": "python",
  "categories": ["syntax", "security"]
}
```

| Field        | Type       | Required | Description                           |
|--------------|------------|----------|---------------------------------------|
| `code`       | string     | Yes      | The source code to review             |
| `language`   | string     | No       | Programming language (default: python)|
| `categories` | string[]   | No       | Categories to check (default: all)    |

### Output

```json
{
  "verdict": "fail",
  "summary": "Found 3 issue(s): 2 error, 1 warning. Verdict: FAIL.",
  "total_issues": 3,
  "issues_by_severity": {
    "info": 0,
    "warning": 1,
    "error": 2,
    "critical": 0
  },
  "issues": [
    {
      "rule_id": "SEC001",
      "category": "security",
      "severity": "error",
      "message": "Use of eval() detected.",
      "line": 5,
      "suggestion": "Replace eval() with ast.literal_eval()."
    }
  ],
  "categories_checked": ["security", "syntax"]
}
```

---

## Project Structure

```
reviewer-agent/
  config.py            -- Configuration (API port, thresholds)
  rules.py             -- Rule definitions and checkers
  reviewer.py          -- Core review engine
  api.py               -- FastAPI HTTP wrapper
  test_reviewer.py     -- Test script
  requirements.txt     -- Python dependencies
  README.md            -- This file
```

---

## Setup

### Prerequisites

- Python 3.10+

### Installation

```bash
cd reviewer-agent
pip install -r requirements.txt
```

### Running the API Server

```bash
python api.py
# Server starts at http://localhost:8015
```

---

## Usage

### HTTP API

| Method | Endpoint  | Description                           |
|--------|-----------|---------------------------------------|
| `GET`  | `/health` | Health check                          |
| `GET`  | `/rules`  | Returns the available rule set        |
| `POST` | `/review` | Review code and return verdict        |

### Running Tests

```bash
python test_reviewer.py
```

Tests cover:
- Clean code that should pass all checks
- Code with syntax errors (should fail, SYN001)
- Code with security violations (should fail, SEC001-SEC007)
- Code with style issues (STY003, STY004)
- Code missing required elements (REQ001-REQ003)
- Category filtering
- Non-Python code handling
- API endpoint functionality

---

## Configuration

| Variable                   | Default    | Description                     |
|----------------------------|------------|---------------------------------|
| `REVIEWER_HOST`            | `0.0.0.0`| API server bind address          |
| `REVIEWER_PORT`            | `8015`    | API server port                  |
| `REVIEWER_MAX_LINE_LENGTH` | `120`     | Maximum allowed line length      |
| `REVIEWER_FAIL_THRESHOLD`  | `error`   | Minimum severity to cause fail   |
