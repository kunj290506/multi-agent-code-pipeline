"""
launch_backend.py — single-window backend launcher
====================================================
Starts ALL Python services in one terminal window:
  - Target App      :8000
  - Planner Agent   :8010
  - RAG Agent       :8011
  - DB Query Agent  :8012
  - DB Executor     :8013
  - CodeGen Agent   :8014
  - Reviewer Agent  :8015
  - Webapp Backend  :8020

Run from the repo root:
    python scripts/launch_backend.py
"""

import os
import signal
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SERVICES = [
    # (label, cwd-relative-to-root, module:app, port)
    ("Target App   ", "target-app",      "app:app",          8000),
    ("Planner      ", "agents/planner",  "api:app",          8010),
    ("RAG          ", "agents/rag",      "api:app",          8011),
    ("DB Query     ", "agents/db",       "api:app",          8012),
    ("DB Executor  ", "agents/db",       "executor_api:app", 8013),
    ("CodeGen      ", "agents/codegen",  "api:app",          8014),
    ("Reviewer     ", "agents/reviewer", "api:app",          8015),
    ("Webapp Backend", "webapp/backend", "main:app",         8020),
]

COLORS = {
    "Target App   ": "\033[96m",   # cyan
    "Planner      ": "\033[93m",   # yellow
    "RAG          ": "\033[94m",   # blue
    "DB Query     ": "\033[95m",   # magenta
    "DB Executor  ": "\033[95m",
    "CodeGen      ": "\033[92m",   # green
    "Reviewer     ": "\033[91m",   # red
    "Webapp Backend": "\033[97m",  # white
}
RESET = "\033[0m"

procs: list[subprocess.Popen] = []


def _tag(label: str) -> str:
    color = COLORS.get(label, "")
    return f"{color}[{label.strip()}]{RESET}"


def start_all() -> None:
    print("\n" + "=" * 60)
    print("  MULTI-AGENT PIPELINE — BACKEND LAUNCHER")
    print("=" * 60)
    for label, rel_cwd, module, port in SERVICES:
        cwd = os.path.join(ROOT, rel_cwd)
        cmd = [
            sys.executable, "-m", "uvicorn",
            module,
            "--host", "0.0.0.0",
            "--port", str(port),
            "--reload",
            "--log-level", "warning",   # suppress per-request noise
        ]
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        procs.append(proc)
        print(f"  {_tag(label)}  started  (pid {proc.pid})  → http://localhost:{port}/docs")

    print("=" * 60)
    print("  All 8 services started in this window.")
    print("  Logs will stream below.  Press Ctrl+C to stop everything.")
    print("=" * 60 + "\n")

    # Stream all stdout/stderr here with labelled prefix
    import threading

    def _stream(proc: subprocess.Popen, label: str) -> None:
        tag = _tag(label)
        assert proc.stdout
        for line in proc.stdout:
            print(f"{tag} {line}", end="", flush=True)

    for (label, *_), proc in zip(SERVICES, procs):
        t = threading.Thread(target=_stream, args=(proc, label), daemon=True)
        t.start()

    # Wait for Ctrl+C
    try:
        while True:
            time.sleep(1)
            # If any process died unexpectedly, report it
            for (label, *_), proc in zip(SERVICES, procs):
                if proc.poll() is not None:
                    print(f"\n{_tag(label)} exited with code {proc.returncode}")
    except KeyboardInterrupt:
        print("\n\nShutting down all services…")
        for proc in procs:
            try:
                proc.terminate()
            except Exception:
                pass
        time.sleep(2)
        for proc in procs:
            if proc.poll() is None:
                proc.kill()
        print("Done.")


if __name__ == "__main__":
    # Windows: handle Ctrl+C on subprocesses
    if sys.platform == "win32":
        signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    start_all()
