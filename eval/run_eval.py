#!/usr/bin/env python3
"""
Evaluation runner for the multi-agent pipeline.

Submits each test case from evaluation_set.json to the webapp backend,
collects metrics from the log files, and writes results_<provider>.csv.

Usage:
    python run_eval.py [--base-url http://localhost:8020] [--timeout 300]
                       [--provider ollama|groq] [--username u] [--password p]
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
POLL_INTERVAL = 5  # seconds between status polls


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

def _get_session(base_url: str, username: str, password: str) -> requests.Session:
    """Login and return a requests.Session carrying the session cookie."""
    session = requests.Session()
    try:
        resp = session.post(
            f"{base_url}/auth/login",
            json={"username": username, "password": password},
            timeout=15,
        )
        if resp.status_code == 200:
            print(f"  Authenticated as '{username}' (HTTP 200)")
            return session
        elif resp.status_code == 401:
            # Try signup if login fails (first run with fresh users.db)
            resp2 = session.post(
                f"{base_url}/auth/signup",
                json={"username": username, "email": f"{username}@eval.local", "password": password},
                timeout=15,
            )
            if resp2.status_code == 200:
                print(f"  Registered + authenticated as '{username}' (HTTP 200)")
                return session
            print(f"  Auth signup failed: {resp2.status_code} {resp2.text[:200]}")
        else:
            print(f"  Auth login failed: {resp.status_code} {resp.text[:200]}")
    except requests.RequestException as exc:
        print(f"  Auth error: {exc}")
    return session  # return unauthenticated session; callers handle 401s


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

def run_case(
    case: dict,
    base_url: str,
    timeout: int,
    provider: str = "ollama",
    session: requests.Session | None = None,
) -> dict:
    """Submit one evaluation case and return a result dict."""
    sess = session or requests.Session()
    case_id = case["id"]
    feature_request = case["feature_request"]

    result: dict = {
        "id": case_id,
        "provider": provider,
        "feature_request": feature_request,
        "agents_called": [],
        "retry_count": 0,
        "final_verdict": "error",
        "total_duration_ms": 0,
        "schema_errors": 0,
        "rate_limit_fallback": False,
        "pass": False,
    }

    # -----------------------------------------------------------------------
    # E12 — empty request; expect HTTP 422
    # -----------------------------------------------------------------------
    if case_id == "E12":
        try:
            resp = sess.post(
                f"{base_url}/runs",
                json={"request": ""},
                timeout=15,
            )
            if resp.status_code == 422:
                result["final_verdict"] = "fail"
                result["pass"] = True
                print(f"  [{case_id}] HTTP {resp.status_code} - 422 received as expected [OK]")
            else:
                result["final_verdict"] = f"unexpected_http_{resp.status_code}"
                print(f"  [{case_id}] UNEXPECTED HTTP {resp.status_code} (expected 422) [FAIL]")
        except requests.RequestException as exc:
            result["final_verdict"] = "error"
            print(f"  [{case_id}] Request error: {exc} [FAIL]")
        return result

    # -----------------------------------------------------------------------
    # All other cases — POST /runs (async, returns request_id immediately)
    # then poll /runs/{id}/status until complete, then read log.
    # -----------------------------------------------------------------------
    body: dict = {"request": feature_request}
    if case.get("project_name"):
        body["project_name"] = case["project_name"]

    try:
        post_resp = sess.post(
            f"{base_url}/runs",
            json=body,
            timeout=30,
        )
        post_resp.raise_for_status()
        request_id = post_resp.json().get("request_id")
    except requests.RequestException as exc:
        print(f"  [{case_id}] POST /runs failed: {exc} [FAIL]")
        return result

    if not request_id:
        print(f"  [{case_id}] No request_id in response [FAIL]")
        return result

    # Poll /runs/{id}/status until no longer "running"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(POLL_INTERVAL)
        try:
            sr = sess.get(f"{base_url}/runs/{request_id}/status", timeout=10)
            if sr.status_code == 200:
                s = sr.json()
                status = s.get("status", "running")
                if status not in ("running", "awaiting_approval"):
                    break
        except requests.RequestException:
            pass
    else:
        print(f"  [{case_id}] Timed out waiting for run to complete [FAIL]")
        return result

    # Fetch the full log (no auth required on /logs endpoints)
    try:
        detail_resp = sess.get(f"{base_url}/logs/{request_id}", timeout=15)
        detail_resp.raise_for_status()
        log = detail_resp.json()
    except requests.RequestException as exc:
        print(f"  [{case_id}] Could not fetch log {request_id}: {exc} [FAIL]")
        return result

    metrics = _extract_metrics(log)
    overall_status = log.get("status") or log.get("overall_status")

    result["agents_called"] = metrics["agents_called"]
    result["retry_count"] = metrics["retry_count"]
    result["final_verdict"] = metrics["final_verdict"]
    result["total_duration_ms"] = metrics["total_duration_ms"]
    result["pass"] = _eval_pass(case, metrics["final_verdict"], overall_status)

    # Schema-error and rate-limit tracking from step data
    schema_errors = 0
    rate_limit_fallback = False
    for step in log.get("steps", []):
        data = step.get("data") or {}
        be = data.get("llm_schema_errors") or []
        schema_errors += len(be)
        if "groq_rate_limit_fallback" in be:
            rate_limit_fallback = True
    result["schema_errors"] = schema_errors
    result["rate_limit_fallback"] = rate_limit_fallback

    status_icon = "[OK]" if result["pass"] else "[FAIL]"
    rl_note = "  [RATE-LIMIT-FALLBACK]" if rate_limit_fallback else ""
    print(
        f"  [{case_id}] verdict={result['final_verdict']}  retries={result['retry_count']}"
        f"  duration={result['total_duration_ms']}ms  schema_errors={schema_errors}"
        f"  pass={result['pass']} {status_icon}{rl_note}"
    )
    return result


# ---------------------------------------------------------------------------
# CSV writer
# ---------------------------------------------------------------------------

def write_csv(results: list[dict], path: Path) -> None:
    """Write results list to a CSV file."""
    fieldnames = [
        "id", "provider", "feature_request", "agents_called",
        "retry_count", "final_verdict", "total_duration_ms",
        "schema_errors", "rate_limit_fallback", "pass",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in results:
            row_copy = dict(row)
            row_copy["agents_called"] = "|".join(row_copy.get("agents_called") or [])
            writer.writerow(row_copy)
    print(f"\nResults written to: {path}")


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------

def print_summary(results: list[dict], provider: str = "") -> None:
    """Print aggregate metrics to stdout."""
    total = len(results)
    passed = sum(1 for r in results if r["pass"])
    failed = total - passed
    durations = [r["total_duration_ms"] for r in results if r["total_duration_ms"] > 0]
    retry_cases = sum(1 for r in results if r["retry_count"] > 0)
    schema_error_cases = sum(1 for r in results if r.get("schema_errors", 0) > 0)
    rate_limit_cases = sum(1 for r in results if r.get("rate_limit_fallback"))

    avg_ms = statistics.mean(durations) if durations else 0
    p50_ms = statistics.median(durations) if durations else 0
    max_ms = max(durations) if durations else 0
    retry_rate = retry_cases / total if total else 0

    label = f"  EVALUATION SUMMARY  [{provider.upper()}]" if provider else "  EVALUATION SUMMARY"
    print("\n" + "=" * 60)
    print(label)
    print("=" * 60)
    print(f"  Total cases         : {total}")
    print(f"  Pass                : {passed}")
    print(f"  Fail                : {failed}")
    print(f"  Pass rate           : {passed / total * 100:.1f}%" if total else "  Pass rate           : n/a")
    print(f"  Avg duration        : {avg_ms:.0f} ms")
    print(f"  p50 duration        : {p50_ms:.0f} ms")
    print(f"  Max duration        : {max_ms:.0f} ms")
    print(f"  Retry rate          : {retry_rate * 100:.1f}% ({retry_cases}/{total} cases)")
    print(f"  Schema error cases  : {schema_error_cases}")
    print(f"  Rate-limit fallbacks: {rate_limit_cases}")
    print("=" * 60)


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
    parser.add_argument(
        "--provider",
        default="",
        help=(
            "Label for this run (e.g. 'ollama' or 'groq'). "
            "Does NOT set LLM_PROVIDER — set that env var on the agent processes before running. "
            "This value is only recorded in results.csv for traceability."
        ),
    )
    parser.add_argument(
        "--output",
        default="",
        help="Override output CSV filename (default: results_{provider}.csv in eval dir).",
    )
    parser.add_argument(
        "--username",
        default="evaluser",
        help="Username for pipeline auth (default: evaluser).",
    )
    parser.add_argument(
        "--password",
        default="evalpass",
        help="Password for pipeline auth (default: evalpass).",
    )
    args = parser.parse_args()

    provider = args.provider or "ollama"
    output_path = Path(args.output) if args.output else EVAL_DIR / f"results_{provider}.csv"

    cases = json.loads(EVALUATION_SET.read_text(encoding="utf-8"))
    print(f"Loaded {len(cases)} evaluation cases from {EVALUATION_SET}")
    print(f"Target: {args.base_url}  timeout: {args.timeout}s  provider-label: {provider}\n")

    # Authenticate once; reuse session cookie for all cases.
    print("Authenticating...")
    session = _get_session(args.base_url, args.username, args.password)
    print()

    results: list[dict] = []
    for case in cases:
        print(f"[{case['id']}] {case['feature_request'][:72] or '(empty)'}...")
        result = run_case(
            case,
            base_url=args.base_url,
            timeout=args.timeout,
            provider=provider,
            session=session,
        )
        results.append(result)

    write_csv(results, output_path)
    print_summary(results, provider=provider)


if __name__ == "__main__":
    main()
