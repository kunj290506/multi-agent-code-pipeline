"""
Reviewer / QA Agent -- Rule Definitions.

Defines the complete rule set used to review generated code:
- Syntax validity
- Required elements (docstrings, type hints)
- Security checks (eval, exec, hardcoded secrets, etc.)
- Style conventions (naming, line length)
"""

import ast
import re

import config


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class Issue:
    """Represents a single issue found during code review."""

    def __init__(
        self,
        rule_id: str,
        category: str,
        severity: str,
        message: str,
        line: int | None = None,
        suggestion: str = "",
    ):
        self.rule_id = rule_id
        self.category = category
        self.severity = severity
        self.message = message
        self.line = line
        self.suggestion = suggestion

    def to_dict(self) -> dict:
        """Serialize the issue to a dictionary."""
        result = {
            "rule_id": self.rule_id,
            "category": self.category,
            "severity": self.severity,
            "message": self.message,
        }
        if self.line is not None:
            result["line"] = self.line
        if self.suggestion:
            result["suggestion"] = self.suggestion
        return result


# ---------------------------------------------------------------------------
# Rule: Syntax validity
# ---------------------------------------------------------------------------

def check_syntax(code: str, language: str = "python") -> list[Issue]:
    """Check if the code is syntactically valid.

    Currently supports Python only. Other languages return no issues
    (syntax checking is skipped).
    """
    if language != "python":
        return []

    issues = []
    try:
        ast.parse(code)
    except SyntaxError as exc:
        issues.append(Issue(
            rule_id="SYN001",
            category="syntax",
            severity="critical",
            message=f"Syntax error: {exc.msg}",
            line=exc.lineno,
            suggestion="Fix the syntax error before proceeding.",
        ))
    return issues


# ---------------------------------------------------------------------------
# Rule: Required elements
# ---------------------------------------------------------------------------

def check_required_elements(code: str, language: str = "python") -> list[Issue]:
    """Check for required structural elements.

    For Python code, checks:
    - Module-level docstring
    - Function/method docstrings
    - Type hints on function arguments
    """
    if language != "python":
        return []

    issues = []

    try:
        tree = ast.parse(code)
    except SyntaxError:
        # Syntax errors are caught by check_syntax; skip structural checks.
        return []

    # Check module docstring.
    if not (tree.body and isinstance(tree.body[0], ast.Expr)
            and isinstance(tree.body[0].value, (ast.Constant, ast.Str))):
        issues.append(Issue(
            rule_id="REQ001",
            category="required_elements",
            severity="warning",
            message="Missing module-level docstring.",
            line=1,
            suggestion="Add a docstring at the top of the module.",
        ))

    # Check function/method docstrings and type hints.
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Check docstring.
            if not (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, (ast.Constant, ast.Str))):
                issues.append(Issue(
                    rule_id="REQ002",
                    category="required_elements",
                    severity="warning",
                    message=f"Function '{node.name}' is missing a docstring.",
                    line=node.lineno,
                    suggestion=f"Add a docstring to function '{node.name}'.",
                ))

            # Check type hints on arguments (skip 'self' and 'cls').
            for arg in node.args.args:
                if arg.arg in ("self", "cls"):
                    continue
                if arg.annotation is None:
                    issues.append(Issue(
                        rule_id="REQ003",
                        category="required_elements",
                        severity="info",
                        message=(
                            f"Argument '{arg.arg}' in function "
                            f"'{node.name}' has no type hint."
                        ),
                        line=node.lineno,
                        suggestion=(
                            f"Add a type annotation to '{arg.arg}'."
                        ),
                    ))

    return issues


# ---------------------------------------------------------------------------
# Rule: Security checks
# ---------------------------------------------------------------------------

# Patterns that indicate potentially dangerous operations.
SECURITY_PATTERNS: list[tuple[str, re.Pattern, str, str]] = [
    (
        "SEC001",
        re.compile(r"\beval\s*\("),
        "Use of eval() detected. This can execute arbitrary code.",
        "Replace eval() with ast.literal_eval() or a safer alternative.",
    ),
    (
        "SEC002",
        re.compile(r"\bexec\s*\("),
        "Use of exec() detected. This can execute arbitrary code.",
        "Avoid exec(); use structured code generation instead.",
    ),
    (
        "SEC003",
        re.compile(r"\bsubprocess\s*\.\s*(call|run|Popen|check_output)\s*\("),
        "Direct subprocess invocation detected.",
        "Validate and sanitize all inputs passed to subprocess calls.",
    ),
    (
        "SEC004",
        re.compile(r"\b__import__\s*\("),
        "Dynamic import via __import__() detected.",
        "Use standard import statements instead of __import__().",
    ),
    (
        "SEC005",
        re.compile(
            r"""(?:password|secret|api_key|token)\s*=\s*["'][^"']{3,}["']""",
            re.IGNORECASE,
        ),
        "Possible hardcoded secret or credential detected.",
        "Use environment variables or a secrets manager instead.",
    ),
    (
        "SEC006",
        re.compile(r"\bos\.system\s*\("),
        "Use of os.system() detected. This is vulnerable to shell injection.",
        "Use subprocess.run() with shell=False instead.",
    ),
    (
        "SEC007",
        re.compile(r"\bpickle\s*\.\s*(loads?|dump)\s*\("),
        "Use of pickle detected. Deserialization of untrusted data is dangerous.",
        "Use JSON or a safer serialization format for untrusted data.",
    ),
]


def check_security(code: str) -> list[Issue]:
    """Check code for security anti-patterns."""
    issues = []
    lines = code.split("\n")

    for line_num, line in enumerate(lines, 1):
        # Skip comments.
        stripped = line.strip()
        if stripped.startswith("#"):
            continue

        for rule_id, pattern, message, suggestion in SECURITY_PATTERNS:
            if pattern.search(line):
                issues.append(Issue(
                    rule_id=rule_id,
                    category="security",
                    severity="error",
                    message=message,
                    line=line_num,
                    suggestion=suggestion,
                ))

    return issues


# ---------------------------------------------------------------------------
# Rule: Style conventions
# ---------------------------------------------------------------------------

# Regex for snake_case function and variable names.
SNAKE_CASE_PATTERN = re.compile(r"^[a-z_][a-z0-9_]*$")


def check_style(code: str, language: str = "python") -> list[Issue]:
    """Check code against style conventions.

    For Python code, checks:
    - Line length
    - Function naming (snake_case)
    - Class naming (PascalCase)
    - Trailing whitespace
    """
    if language != "python":
        return []

    issues = []
    lines = code.split("\n")
    max_len = config.MAX_LINE_LENGTH

    # Line length and trailing whitespace.
    for line_num, line in enumerate(lines, 1):
        if len(line) > max_len:
            issues.append(Issue(
                rule_id="STY001",
                category="style",
                severity="info",
                message=(
                    f"Line exceeds {max_len} characters "
                    f"({len(line)} characters)."
                ),
                line=line_num,
                suggestion=f"Shorten the line to {max_len} characters or less.",
            ))

        if line != line.rstrip():
            issues.append(Issue(
                rule_id="STY002",
                category="style",
                severity="info",
                message="Trailing whitespace detected.",
                line=line_num,
                suggestion="Remove trailing whitespace.",
            ))

    # AST-based naming checks.
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return issues

    for node in ast.walk(tree):
        # Function naming: should be snake_case.
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_") and not SNAKE_CASE_PATTERN.match(node.name):
                issues.append(Issue(
                    rule_id="STY003",
                    category="style",
                    severity="warning",
                    message=(
                        f"Function '{node.name}' does not follow "
                        f"snake_case convention."
                    ),
                    line=node.lineno,
                    suggestion=f"Rename '{node.name}' to use snake_case.",
                ))

        # Class naming: should be PascalCase (first letter uppercase).
        if isinstance(node, ast.ClassDef):
            if node.name[0].islower():
                issues.append(Issue(
                    rule_id="STY004",
                    category="style",
                    severity="warning",
                    message=(
                        f"Class '{node.name}' does not follow "
                        f"PascalCase convention."
                    ),
                    line=node.lineno,
                    suggestion=f"Rename '{node.name}' to use PascalCase.",
                ))

    return issues


# ---------------------------------------------------------------------------
# Rule registry
# ---------------------------------------------------------------------------

# All available rules keyed by category.
RULE_REGISTRY: dict[str, dict] = {
    "syntax": {
        "description": "Checks that the code parses without syntax errors.",
        "rules": [
            {"id": "SYN001", "description": "Syntax error detected."},
        ],
    },
    "required_elements": {
        "description": "Checks for required structural elements.",
        "rules": [
            {"id": "REQ001", "description": "Missing module docstring."},
            {"id": "REQ002", "description": "Missing function docstring."},
            {"id": "REQ003", "description": "Missing type hint on argument."},
        ],
    },
    "security": {
        "description": "Checks for security anti-patterns.",
        "rules": [
            {"id": "SEC001", "description": "Use of eval()."},
            {"id": "SEC002", "description": "Use of exec()."},
            {"id": "SEC003", "description": "Direct subprocess invocation."},
            {"id": "SEC004", "description": "Dynamic import via __import__()."},
            {"id": "SEC005", "description": "Hardcoded secret or credential."},
            {"id": "SEC006", "description": "Use of os.system()."},
            {"id": "SEC007", "description": "Use of pickle with untrusted data."},
        ],
    },
    "style": {
        "description": "Checks code style conventions.",
        "rules": [
            {"id": "STY001", "description": "Line too long."},
            {"id": "STY002", "description": "Trailing whitespace."},
            {"id": "STY003", "description": "Function not in snake_case."},
            {"id": "STY004", "description": "Class not in PascalCase."},
        ],
    },
}
