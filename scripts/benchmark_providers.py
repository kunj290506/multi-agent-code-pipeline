"""
benchmark_providers.py — Runs the full eval/evaluation_set.json twice:
  once with LLM_PROVIDER=ollama and once with LLM_PROVIDER=groq.

Handles service restart between runs so LLM_PROVIDER is correct in every
agent process.  Produces eval/results_ollama.csv and eval/results_groq.csv,
then prints a side-by-side comparison table.

Usage (from repo root):
    python scripts/benchmark_providers.py

Prerequisites:
    GROQ_API_KEY must be set in the environment, or passed via --groq-key.
    Ollama must be running on localhost:11434.
    All Python requirements must already be installed.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVAL_SCRIPT = ROOT / "eval" / "run_eval.py"

# ---------------------------------------------------------------------------
# Service definitions — agents + webapp only (target-app at :8000 is the
# demo app, not part of the agent pipeline; its app.py may not exist).
# ---------------------------------------------------------------------------
SERVICES = [
    ("Planner",       ROOT / "agents/planner", "api:app",          8010, "/health"),
    ("RAG",           ROOT / "agents/rag",     "api:app",          8011, "/health"),
    ("DB Query",      ROOT / "agents/db",      "api:app",          8012, "/health"),
    ("DB Executor",   ROOT / "agents/db",      "executor_api:app", 8013, "/health"),
    ("CodeGen",       ROOT / "agents/codegen", "api:app",          8014, "/health"),
    ("Reviewer",      ROOT / "agents/reviewer","api:app",          8015, "/health"),
    ("Webapp Backend",ROOT / "webapp/backend", "main:app",         8020, "/health"),
]

GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
RESET  = "\033[0m"


# ---------------------------------------------------------------------------
# Port helpers
# ---------------------------------------------------------------------------

def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        try:
            s.connect(("127.0.0.1", port))
            return False
        except (ConnectionRefusedError, OSError):
            return True


def _kill_port(port: int) -> None:
    """Best-effort: kill whatever process is bound to port (Windows)."""
    try:
        out = subprocess.check_output(
            ["netstat", "-ano"], text=True, stderr=subprocess.DEVNULL
        )
        for line in out.splitlines():
            if f":{port} " in line and "LISTENING" in line:
                parts = line.split()
                pid = int(parts[-1])
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(pid)],
                    check=False, capture_output=True,
                )
                break
    except Exception:
        pass


def _wait_for_port(port: int, timeout: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        url = f"http://127.0.0.1:{port}/health"
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.8)
    return False


# ---------------------------------------------------------------------------
# Service lifecycle
# ---------------------------------------------------------------------------

_procs: list[subprocess.Popen] = []


def stop_services() -> None:
    """Terminate all tracked service processes."""
    print(f"\n{YELLOW}[benchmark] Stopping services...{RESET}")
    for proc in _procs:
        try:
            proc.terminate()
        except Exception:
            pass
    time.sleep(2)
    for proc in _procs:
        if proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass
    _procs.clear()

    # Also kill anything still on the service ports (stale uvicorn workers).
    for _, _, _, port, _ in SERVICES:
        if not _port_free(port):
            _kill_port(port)
    time.sleep(1)
    print(f"{GREEN}[benchmark] All services stopped.{RESET}")


def start_services(extra_env: dict[str, str] | None = None) -> bool:
    """Start all services with extra_env merged into the environment."""
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)

    print(f"\n{CYAN}[benchmark] Starting services (LLM_PROVIDER={env.get('LLM_PROVIDER','ollama')})...{RESET}")

    for label, cwd, module, port, health_path in SERVICES:
        # Free port if something else is already there.
        if not _port_free(port):
            print(f"  {YELLOW}[!] Port {port} occupied — killing stale process...{RESET}")
            _kill_port(port)
            time.sleep(1)

        cmd = [
            sys.executable, "-m", "uvicorn",
            module,
            "--host", "0.0.0.0",
            "--port", str(port),
            "--log-level", "warning",
        ]
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _procs.append(proc)

        healthy = _wait_for_port(port, timeout=90)
        if not healthy:
            print(f"  {RED}[FAIL] {label} (:{port}) did not come up within 90s.{RESET}")
            stop_services()
            return False
        print(f"  {GREEN}[OK]{RESET}  {label:<20} :{port}")

    print(f"{GREEN}[benchmark] All services healthy.{RESET}\n")
    return True


# ---------------------------------------------------------------------------
# Run one full eval pass
# ---------------------------------------------------------------------------

def run_eval(provider: str) -> Path:
    """Run the full evaluation set and return the results CSV path."""
    output = ROOT / "eval" / f"results_{provider}.csv"
    cmd = [
        sys.executable,
        str(EVAL_SCRIPT),
        "--provider", provider,
        "--output", str(output),
        "--timeout", "360",
        "--username", "evaluser",
        "--password", "evalpass",
    ]
    print(f"\n{CYAN}{'='*60}{RESET}")
    print(f"{CYAN}  RUNNING EVAL — provider={provider.upper()}{RESET}")
    print(f"{CYAN}{'='*60}{RESET}\n")
    result = subprocess.run(cmd, cwd=str(ROOT))
    if result.returncode != 0:
        print(f"{YELLOW}[WARN] eval script exited with code {result.returncode}{RESET}")
    return output


# ---------------------------------------------------------------------------
# Compare and print table
# ---------------------------------------------------------------------------

def load_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def print_comparison(ollama_rows: list[dict], groq_rows: list[dict]) -> None:
    """Print a side-by-side comparison table."""
    by_id_o = {r["id"]: r for r in ollama_rows}
    by_id_g = {r["id"]: r for r in groq_rows}
    all_ids = sorted(set(by_id_o) | set(by_id_g), key=lambda x: int(x[1:]))

    header = (
        f"{'Case':<5} | {'Provider':<8} | {'ms':>7} | {'Retries':>7} | "
        f"{'Verdict':<12} | {'Schema':>6} | {'RL':>4} | {'Pass':>5} | Notes"
    )
    sep = "-" * len(header)
    print(f"\n{'='*len(header)}")
    print("  BENCHMARK COMPARISON TABLE")
    print(f"{'='*len(header)}")
    print(header)
    print(sep)

    for cid in all_ids:
        for prov, rows in [("ollama", by_id_o), ("groq", by_id_g)]:
            r = rows.get(cid)
            if r is None:
                print(f"{cid:<5} | {prov:<8} | {'N/A':>7} | {'N/A':>7} | {'N/A':<12} | {'N/A':>6} | {'N/A':>4} | {'N/A':>5} |")
                continue
            ms = r.get("total_duration_ms", "0")
            retries = r.get("retry_count", "0")
            verdict = r.get("final_verdict", "?")[:12]
            schema = r.get("schema_errors", "0")
            rl = "YES" if r.get("rate_limit_fallback", "").lower() == "true" else "no"
            passed = r.get("pass", "False")
            pass_str = "PASS" if str(passed).lower() == "true" else "FAIL"
            print(
                f"{cid:<5} | {prov:<8} | {ms:>7} | {retries:>7} | "
                f"{verdict:<12} | {schema:>6} | {rl:>4} | {pass_str:>5} |"
            )
        print(sep)

    # Aggregate summary
    print()
    for prov, rows in [("ollama", ollama_rows), ("groq", groq_rows)]:
        if not rows:
            continue
        total = len(rows)
        passed = sum(1 for r in rows if str(r.get("pass", "")).lower() == "true")
        durations = [int(r["total_duration_ms"]) for r in rows if r.get("total_duration_ms", "0").isdigit() and int(r["total_duration_ms"]) > 0]
        avg_ms = int(sum(durations) / len(durations)) if durations else 0
        total_schema = sum(int(r.get("schema_errors", 0)) for r in rows)
        rl_count = sum(1 for r in rows if str(r.get("rate_limit_fallback", "")).lower() == "true")
        print(
            f"  {prov.upper():<8}: {passed}/{total} pass  "
            f"avg={avg_ms}ms  schema_errors={total_schema}  rate_limit_fallbacks={rl_count}"
        )
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark Ollama vs Groq on the eval set.")
    parser.add_argument("--groq-key", default="", help="Groq API key (default: from GROQ_API_KEY env)")
    parser.add_argument("--groq-model", default="qwen/qwen3.8-27b", help="Groq model ID")
    parser.add_argument("--ollama-only", action="store_true", help="Run only the Ollama pass")
    parser.add_argument("--groq-only", action="store_true", help="Run only the Groq pass")
    args = parser.parse_args()

    groq_key = args.groq_key or os.getenv("GROQ_API_KEY", "")
    if not args.ollama_only and not groq_key:
        print(f"{RED}ERROR: GROQ_API_KEY not set and --groq-key not provided.{RESET}")
        sys.exit(1)

    try:
        # ── Run 1: Ollama ──────────────────────────────────────────────────
        if not args.groq_only:
            stop_services()
            ok = start_services({"LLM_PROVIDER": "ollama"})
            if not ok:
                print(f"{RED}Aborting: services failed to start for Ollama run.{RESET}")
                sys.exit(1)
            ollama_csv = run_eval("ollama")
        else:
            ollama_csv = ROOT / "eval" / "results_ollama.csv"

        # ── Run 2: Groq ────────────────────────────────────────────────────
        if not args.ollama_only:
            stop_services()
            ok = start_services({
                "LLM_PROVIDER": "groq",
                "GROQ_API_KEY": groq_key,
                "GROQ_MODEL": args.groq_model,
            })
            if not ok:
                print(f"{RED}Aborting: services failed to start for Groq run.{RESET}")
                sys.exit(1)
            groq_csv = run_eval("groq")
        else:
            groq_csv = ROOT / "eval" / "results_groq.csv"

    finally:
        stop_services()

    # ── Print comparison ───────────────────────────────────────────────────
    ollama_rows = load_csv(ollama_csv)
    groq_rows = load_csv(groq_csv)
    print_comparison(ollama_rows, groq_rows)

    print(f"  Full results: {ollama_csv}")
    print(f"               {groq_csv}\n")


if __name__ == "__main__":
    if sys.platform == "win32":
        signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    main()
