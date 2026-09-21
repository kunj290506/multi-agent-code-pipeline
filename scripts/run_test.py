"""
Part 4 verification script — runs 3 clean pipeline runs and reports
per-agent timing for each. Run from the repo root:
    python scripts/run_test.py
"""
import httpx
import json
import sys
import time

BASE = "http://localhost:8020"
REQUESTS = [
    "Build a simple calculator app",
    "Add a dark mode toggle to the app",
    "Build a student attendance tracker",
]

client = httpx.Client(timeout=600, follow_redirects=True)

# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------
print("Logging in...")
r = client.post(f"{BASE}/auth/login", json={"username": "testuser", "password": "testpass"})
if r.status_code != 200:
    print(f"Login failed: {r.status_code} {r.text}")
    sys.exit(1)
print(f"  OK  (status {r.status_code})\n")


# ---------------------------------------------------------------------------
# Run helper
# ---------------------------------------------------------------------------
def run_pipeline(request_text: str, run_num: int) -> dict:
    print(f"{'='*60}")
    print(f"RUN {run_num}: {request_text}")
    print(f"{'='*60}")
    t0 = time.monotonic()

    start = client.post(f"{BASE}/runs", json={"request": request_text})
    if start.status_code != 202:
        print(f"  START FAILED: {start.status_code} {start.text[:400]}")
        return {"status": "start_failed", "elapsed_ms": 0}

    rid = start.json()["request_id"]
    print(f"  request_id : {rid}")

    prev_steps = 0
    final_state: dict = {}
    while True:
        time.sleep(2)
        sr = client.get(f"{BASE}/runs/{rid}/status")
        if sr.status_code != 200:
            print(f"  Status poll error: {sr.status_code} {sr.text[:200]}")
            break
        s = sr.json()
        steps = s.get("steps", [])

        # Print each new step as it arrives
        for step in steps[prev_steps:]:
            dur = step.get("duration_ms")
            agent = step["agent"].ljust(20)
            status = step["status"].ljust(8)
            summary = (step.get("output_summary") or "")[:80]
            print(f"  {agent} [{status}]  {dur}ms  {summary}")
        prev_steps = len(steps)

        if s["status"] not in ("running", "awaiting_approval"):
            elapsed = int((time.monotonic() - t0) * 1000)
            final_state = s
            print(f"\n  STATUS  : {s['status'].upper()}")
            print(f"  ELAPSED : {elapsed}ms  ({elapsed/1000:.1f}s)")
            print(f"  BACKEND : {s.get('total_duration_ms')}ms")
            print()
            print("  Per-agent timing:")
            for step in steps:
                a = step["agent"].ljust(20)
                d = str(step.get("duration_ms", "N/A")).rjust(8)
                attempt = step.get("attempt_number", 1)
                verdict = f"  verdict={step['verdict']}" if step.get("verdict") else ""
                print(f"    {a}  {d}ms  attempt={attempt}{verdict}")
            return {"status": s["status"], "elapsed_ms": elapsed, "steps": steps, "rid": rid}

    return {"status": "poll_failed", "elapsed_ms": 0}


# ---------------------------------------------------------------------------
# 3 runs
# ---------------------------------------------------------------------------
results = []
for i, req in enumerate(REQUESTS, 1):
    result = run_pipeline(req, i)
    results.append(result)
    print()
    # Brief pause between runs so the workspace clears
    if i < len(REQUESTS):
        time.sleep(3)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print("=" * 60)
print("SUMMARY")
print("=" * 60)
for i, (req, res) in enumerate(zip(REQUESTS, results), 1):
    status = res["status"].upper()
    elapsed = res.get("elapsed_ms", 0)
    print(f"  Run {i}: [{status:10s}]  {elapsed}ms ({elapsed/1000:.1f}s)  — {req}")

success = sum(1 for r in results if r["status"] == "success")
print(f"\n  {success}/{len(results)} runs succeeded")
