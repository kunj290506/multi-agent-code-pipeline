"""
Reviewer / QA Agent Configuration.

Centralizes all configurable parameters for the code review service.
"""

import os

# ---------------------------------------------------------------------------
# API server
# ---------------------------------------------------------------------------
API_HOST: str = os.getenv("REVIEWER_HOST", "0.0.0.0")
API_PORT: int = int(os.getenv("REVIEWER_PORT", "8015"))

# ---------------------------------------------------------------------------
# Review settings
# ---------------------------------------------------------------------------

# Maximum line length for style checks.
MAX_LINE_LENGTH: int = int(os.getenv("REVIEWER_MAX_LINE_LENGTH", "120"))

# Severity threshold: issues at or above this level cause a FAIL verdict.
# Levels: "info" < "warning" < "error" < "critical"
FAIL_THRESHOLD: str = os.getenv("REVIEWER_FAIL_THRESHOLD", "error")

# Severity ordering for comparisons.
SEVERITY_ORDER: dict[str, int] = {
    "info": 0,
    "warning": 1,
    "error": 2,
    "critical": 3,
}
