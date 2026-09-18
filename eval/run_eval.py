#!/usr/bin/env python3
"""
Evaluation runner for the multi-agent pipeline.

Submits each test case from evaluation_set.json to the webapp backend,
collects metrics from the log files, and writes results.csv.

Usage:
    python run_eval.py [--base-url http://localhost:8020] [--timeout 300]
"""

import argparse
import csv
import json
import statistics
import time
from pathlib import Path

import requests


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EVAL_DIR = Path(__file__).parent
EVALUATION_SET = EVAL_DIR / "evaluation_set.json"
RESULTS_CSV = EVAL_DIR / "results.csv"
POLL_INTERVAL = 5  # seconds between GET /logs polls


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _known_agent_names() -> list[str]:
    """Canonical agent name tokens used in step records."""
    return [
        "planner-agent",
        "rag-agent",
        "codegen-agent",
        "reviewer-agent",
        "db-agent",
    ]


def _extract_metrics(log: dict) -> dict:
    """Pull agents_called, retry_count, final_verdict, total_duration_ms from a run log."""
    steps = log.get("steps", [])

    # Unique agent names — normalise to lower-case tokens matching canonical names
    agents_seen: list[str] = []
    agents_set: set[str] = set()
    for step in steps:
        raw = step.get("agent", "")
        name = raw.lower().strip()
        for canon in _known_agent_names():
            if canon in name and canon not in agents_set:
                agents_set.add(canon)
                agents_seen.append(canon)

    # Retry count — steps where attempt_number > 1
    retry_count = sum(
        1 for step in steps
        if isinstance(step.get("attempt_number"), int) and step["attempt_number"] > 1
    )

    # Final verdict — last reviewer step data, or overall_status
    final_verdict = log.get("status") or log.get("overall_status") or "unknown"
    for step in reversed(steps):
        data = step.get("data") or {}
        verdict = data.get("verdict")
        if verdict:
            final_verdict = verdict
            break

    total_duration_ms = log.get("total_duration_ms") or 0

    return {
        "agents_called": agents_seen,
        "retry_count": retry_count,
        "final_verdict": final_verdict,
        "total_duration_ms": total_duration_ms,
    }


def _eval_pass(case: dict, final_verdict: str, overall_status: str | None) -> bool:
    """Determine whether a case result counts as a pass for the eval harness."""
    expected = case["expected_verdict"]
    if expected == final_verdict:
        return True
    # For non-adversarial happy-path cases: overall_status=="success" also counts
    if not case["adversarial"] and overall_status == "success":
        return True
    return False


# ---------------------------------------------------------------------------
# Core runner
# ---------------------------------------------------------------------------

def run_case(case: dict, base_url: str, timeout: int) -> dict:
    """Submit one evaluation case and return a result dict."""
    case_id = case["id"]
    feature_request = case["feature_request"]

    result: dict = {
        "id": case_id,
        "feature_request": feature_request,
        "agents_called": [],
        "retry_count": 0,
        "final_verdict": "error",
        "total_duration_ms": 0,
        "pass": False,
    }

    # -----------------------------------------------------------------------
    # E12 — empty request; expect HTTP 422
    # -----------------------------------------------------------------------
    if case_id == "E12":
        try:
            resp = requests.post(
                f"{base_url}/request",
                json={"request": ""},
                timeout=15,
            )
            if resp.status_code == 422:
                result["final_verdict"] = "fail"
                result["pass"] = True
                print(f"  [{case_id}] HTTP {resp.status_code} — 422 received as expected ✓")
            else:
                result["final_verdict"] = f"unexpected_http_{resp.status_code}"
                print(f"  [{case_id}] UNEXPECTED HTTP {resp.status_code} (expected 422) ✗")
        except requests.RequestException as exc:
            result["final_verdict"] = "error"
            print(f"  [{case_id}] Request error: {exc} ✗")
        return result

    # -----------------------------------------------------------------------
    # All other cases — POST /request then poll /logs
    # -----------------------------------------------------------------------
    body: dict = {"request": feature_request}
    # If the case has a project_name, forward it so a named workspace is created.
    if case.get("project_name"):
        body["project_name"] = case["project_name"]

    try:
        post_resp = requests.post(
            f"{base_url}/request",
            json=body,
            timeout=30,
        )
        post_resp.raise_for_status()
        post_data = post_resp.json()
    except requests.RequestException as exc:
        print(f"  [{case_id}] POST failed: {exc} ✗")
        return result

    # Snapshot the log list *before* our request to detect new entries
    try:
        before_resp = requests.get(f"{base_url}/logs", timeout=10)
        before_resp.raise_for_status()
        known_ids = {entry.get("request_id") for entry in before_resp.json()}
    except requests.RequestException:
        known_ids = set()

    # Poll until a new log entry appears
    request_id: str | None = None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(POLL_INTERVAL)
        try:
            logs_resp = requests.get(f"{base_url}/logs", timeout=10)
            logs_resp.raise_for_status()
            entries = logs_resp.json()
        except requests.RequestException:
            continue

        for entry in entries:
            rid = entry.get("request_id")
            if rid and rid not in known_ids:
                # Check if the run is complete (overall_status != "running")
                overall = entry.get("overall_status") or entry.get("status") or ""
                if overall != "running":
                    request_id = rid
                    break
        if request_id:
            break

    if not request_id:
        print(f"  [{case_id}] Timed out waiting for log entry ✗")
        return result

    # Fetch the full log
    try:
        detail_resp = requests.get(f"{base_url}/logs/{request_id}", timeout=15)
        detail_resp.raise_for_status()
        log = detail_resp.json()
    except requests.RequestException as exc:
        print(f"  [{case_id}] Could not fetch log {request_id}: {exc} ✗")
        return result

    metrics = _extract_metrics(log)
    overall_status = log.get("status") or log.get("overall_status")

    result["agents_called"] = metrics["agents_called"]
    result["retry_count"] = metrics["retry_count"]
    result["final_verdict"] = metrics["final_verdict"]
    result["total_duration_ms"] = metrics["total_duration_ms"]
    result["pass"] = _eval_pass(case, metrics["final_verdict"], overall_status)

    status_icon = "✓" if result["pass"] else "✗"
    print(
        f"  [{case_id}] verdict={result['final_verdict']}  retries={result['retry_count']}"
        f"  duration={result['total_duration_ms']}ms  pass={result['pass']} {status_icon}"
    )
    return result


# ---------------------------------------------------------------------------
# CSV writer
# ---------------------------------------------------------------------------

def write_csv(results: list[dict], path: Path) -> None:
    """Write results list to a CSV file."""
    fieldnames = [
        "id", "feature_request", "agents_called",
        "retry_count", "final_verdict", "total_duration_ms", "pass",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in results:
            row_copy = dict(row)
            row_copy["agents_called"] = "|".join(row_copy.get("agents_called") or [])
            writer.writerow(row_copy)
    print(f"\nResults written to: {path}")


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------

def print_summary(results: list[dict]) -> None:
    """Print aggregate metrics to stdout."""
    total = len(results)
    passed = sum(1 for r in results if r["pass"])
    failed = total - passed
    durations = [r["total_duration_ms"] for r in results if r["total_duration_ms"] > 0]
    retry_cases = sum(1 for r in results if r["retry_count"] > 0)

    avg_ms = statistics.mean(durations) if durations else 0
    p50_ms = statistics.median(durations) if durations else 0
    max_ms = max(durations) if durations else 0
    retry_rate = retry_cases / total if total else 0

    print("\n" + "=" * 52)
    print("  EVALUATION SUMMARY")
    print("=" * 52)
    print(f"  Total cases   : {total}")
    print(f"  Pass          : {passed}")
    print(f"  Fail          : {failed}")
    print(f"  Pass rate     : {passed / total * 100:.1f}%" if total else "  Pass rate     : n/a")
    print(f"  Avg duration  : {avg_ms:.0f} ms")
    print(f"  p50 duration  : {p50_ms:.0f} ms")
    print(f"  Max duration  : {max_ms:.0f} ms")
    print(f"  Retry rate    : {retry_rate * 100:.1f}% ({retry_cases}/{total} cases)")
    print("=" * 52)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the multi-agent pipeline evaluation set."
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8020",
        help="Base URL of the webapp backend (default: http://localhost:8020)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Per-case timeout in seconds waiting for a log entry (default: 300)",
    )
    args = parser.parse_args()

    cases = json.loads(EVALUATION_SET.read_text(encoding="utf-8"))
    print(f"Loaded {len(cases)} evaluation cases from {EVALUATION_SET}")
    print(f"Target: {args.base_url}  timeout: {args.timeout}s\n")

    results: list[dict] = []
    for case in cases:
        print(f"[{case['id']}] {case['feature_request'][:72] or '(empty)'}...")
        result = run_case(case, base_url=args.base_url, timeout=args.timeout)
        results.append(result)

    write_csv(results, RESULTS_CSV)
    print_summary(results)


if __name__ == "__main__":
    main()
