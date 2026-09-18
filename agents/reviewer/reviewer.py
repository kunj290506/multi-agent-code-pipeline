"""
Reviewer / QA Agent -- Core Review Engine.

Runs all enabled rules against input code, collects issues with severity,
category, and line information, and computes an overall pass/fail verdict.
"""

import config
import rules


def review_code(
    code: str,
    language: str = "python",
    categories: list[str] | None = None,
) -> dict:
    """Review code against the defined rule set.

    Args:
        code: The source code to review.
        language: The programming language of the code.
        categories: Optional list of rule categories to run. If None,
                    all categories are run. Valid categories:
                    'syntax', 'required_elements', 'security', 'style'.

    Returns:
        A structured review result dict with keys:
        - verdict: "pass" or "fail"
        - summary: Human-readable summary string
        - total_issues: Total number of issues found
        - issues_by_severity: Count of issues per severity level
        - issues: List of issue dicts
        - categories_checked: List of categories that were checked
    """
    all_categories = {"syntax", "required_elements", "security", "style"}

    if categories is not None:
        active_categories = set(categories) & all_categories
    else:
        active_categories = all_categories

    all_issues: list[rules.Issue] = []

    # Run each active category's checker.
    if "syntax" in active_categories:
        all_issues.extend(rules.check_syntax(code, language))

    # Only run structural / semantic checks if syntax passes.
    syntax_ok = not any(
        issue.category == "syntax" for issue in all_issues
    )

    if syntax_ok:
        if "required_elements" in active_categories:
            all_issues.extend(rules.check_required_elements(code, language))
        if "security" in active_categories:
            all_issues.extend(rules.check_security(code))
        if "style" in active_categories:
            all_issues.extend(rules.check_style(code, language))

    # Compute severity counts.
    severity_counts = {"info": 0, "warning": 0, "error": 0, "critical": 0}
    for issue in all_issues:
        severity_counts[issue.severity] = (
            severity_counts.get(issue.severity, 0) + 1
        )

    # Determine verdict based on the configured fail threshold.
    threshold_level = config.SEVERITY_ORDER.get(config.FAIL_THRESHOLD, 2)
    has_failing_issue = any(
        config.SEVERITY_ORDER.get(issue.severity, 0) >= threshold_level
        for issue in all_issues
    )
    verdict = "fail" if has_failing_issue else "pass"

    # Build summary.
    total = len(all_issues)
    if total == 0:
        summary = "No issues found. Code passes all checks."
    else:
        parts = []
        for sev in ("critical", "error", "warning", "info"):
            count = severity_counts[sev]
            if count > 0:
                parts.append(f"{count} {sev}")
        summary = (
            f"Found {total} issue(s): {', '.join(parts)}. "
            f"Verdict: {verdict.upper()}."
        )

    return {
        "verdict": verdict,
        "summary": summary,
        "total_issues": total,
        "issues_by_severity": severity_counts,
        "issues": [issue.to_dict() for issue in all_issues],
        "categories_checked": sorted(active_categories),
    }
