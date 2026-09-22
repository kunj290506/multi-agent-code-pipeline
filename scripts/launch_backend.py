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

Changes vs original:
  - FIX 3: Pre-flight port check — reports and kills any stale process still
            bound to a service port before attempting to start.
  - FIX 2: Startup sequencer — after spawning each uvicorn process, polls
            its /health endpoint with timeout+backoff before moving on.
            If a service fails to come up, stops the whole launch and prints
            exactly which service failed and its last startup output.
  - Crash monitor still runs in the main loop, unchanged behaviour.

Run from the repo root:
    python scripts/launch_backend.py
"""

import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SERVICES = [
    # (label, cwd-relative-to-root, module:app, port, health-path)
    ("Planner      ", "agents/planner",  "api:app",          8010, "/health"),
    ("RAG          ", "agents/rag",      "api:app",          8011, "/health"),
    ("DB Query     ", "agents/db",       "api:app",          8012, "/health"),
    ("DB Executor  ", "agents/db",       "executor_api:app", 8013, "/health"),
    ("CodeGen      ", "agents/codegen",  "api:app",          8014, "/health"),
    ("Reviewer     ", "agents/reviewer", "api:app",          8015, "/health"),
    ("Webapp Backend", "webapp/backend", "main:app",         8020, "/health"),
]

COLORS = {
    "Planner      ": "\033[93m",   # yellow
    "RAG          ": "\033[94m",   # blue
    "DB Query     ": "\033[95m",   # magenta
    "DB Executor  ": "\033[95m",
    "CodeGen      ": "\033[92m",   # green
    "Reviewer     ": "\033[91m",   # red
    "Webapp Backend": "\033[97m",  # white
}
RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RESET  = "\033[0m"

# How long to wait for each service to pass its health check.
HEALTH_TIMEOUT_S: int  = int(os.getenv("LAUNCH_HEALTH_TIMEOUT", "180"))
# Seconds between health-poll retries.
HEALTH_POLL_INTERVAL_S: float = 1.0

RELOAD_ARGS = ["--reload"] if os.getenv("PIPELINE_RELOAD") == "1" else []

procs: list[subprocess.Popen] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tag(label: str) -> str:
    color = COLORS.get(label, "")
    return f"{color}[{label.strip()}]{RESET}"


def _port_owner_pid(port: int) -> int | None:
    """Return the PID bound to *port*, or None if the port is free."""
    # Use a raw socket connect to detect if anything is listening.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.connect(("127.0.0.1", port))
            # Something answered — now find its PID via netstat.
            try:
                out = subprocess.check_output(
                    ["netstat", "-ano"],
                    text=True,
                    stderr=subprocess.DEVNULL,
                )
                for line in out.splitlines():
                    if f":{port} " in line and "LISTENING" in line:
                        parts = line.split()
                        return int(parts[-1])
            except Exception:
                return -1   # port occupied but PID unknown
        except (ConnectionRefusedError, OSError):
            return None


def _kill_pid(pid: int) -> None:
    """Best-effort kill of a process by PID (Windows + Unix)."""
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                           check=False, capture_output=True)
        else:
            os.kill(pid, signal.SIGKILL)
    except Exception:
        pass


def _preflight_ports() -> bool:
    """
    FIX 3 — Check every service port is free before launch.

    For each occupied port:
      - If we can identify the PID, kill it and confirm the port freed.
      - If we cannot identify the PID, print an error and return False
        so the caller aborts rather than trying to bind a blocked port.

    Returns True if all ports are clear, False if any could not be freed.
    """
    print(f"\n{YELLOW}[Preflight] Checking service ports…{RESET}")
    all_clear = True
    for label, _, _, port, _ in SERVICES:
        pid = _port_owner_pid(port)
        if pid is None:
            print(f"  {GREEN}[OK]{RESET}  :{port}  free")
            continue
        if pid == -1:
            print(
                f"  {RED}[!!]  :{port}  OCCUPIED (PID unknown) -- "
                f"cannot free automatically.  Kill the process on port {port} "
                f"manually and re-run.{RESET}"
            )
            all_clear = False
            continue
        print(
            f"  {YELLOW}[!]  :{port}  occupied by PID {pid} -- killing stale process...{RESET}"
        )
        _kill_pid(pid)
        # Wait up to 3 s for the port to free.
        freed = False
        for _ in range(6):
            time.sleep(0.5)
            if _port_owner_pid(port) is None:
                freed = True
                break
        if freed:
            print(f"       PID {pid} killed.  :{port} is now free.")
        else:
            print(
                f"  {RED}[!!]  :{port}  still occupied after killing PID {pid}.  "
                f"Free the port manually and re-run.{RESET}"
            )
            all_clear = False
    return all_clear


def _wait_healthy(label: str, port: int, health_path: str, proc: subprocess.Popen) -> bool:
    """
    FIX 2 — Poll GET http://localhost:{port}{health_path} until 200 or timeout.

    Returns True if the service came up healthy within HEALTH_TIMEOUT_S.
    Returns False otherwise (process died or timed out).
    """
    url = f"http://127.0.0.1:{port}{health_path}"
    deadline = time.monotonic() + HEALTH_TIMEOUT_S
    attempt = 0
    while time.monotonic() < deadline:
        # Bail immediately if the process already died.
        if proc.poll() is not None:
            return False
        attempt += 1
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(HEALTH_POLL_INTERVAL_S)
    return False


# ---------------------------------------------------------------------------
# Main launcher
# ---------------------------------------------------------------------------

def start_all() -> None:
    print("\n" + "=" * 60)
    print("  MULTI-AGENT PIPELINE — BACKEND LAUNCHER")
    print("=" * 60)

    # ── FIX 3: Port pre-flight ───────────────────────────────────────────────
    if not _preflight_ports():
        print(
            f"\n{RED}LAUNCH ABORTED — one or more ports could not be freed.{RESET}\n"
            "Free the conflicting port(s) listed above and re-run.\n"
        )
        sys.exit(1)

    print()

    # ── FIX 2: Sequential start with health-poll ─────────────────────────────
    for label, rel_cwd, module, port, health_path in SERVICES:
        cwd = os.path.join(ROOT, rel_cwd)
        cmd = [
            sys.executable, "-m", "uvicorn",
            module,
            "--host", "0.0.0.0",
            "--port", str(port),
            "--log-level", "warning",
        ] + RELOAD_ARGS
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        procs.append(proc)
        print(f"  {_tag(label)}  starting (pid {proc.pid}) on :{port}…", end="", flush=True)

        healthy = _wait_healthy(label, port, health_path, proc)
        if not healthy:
            # Collect whatever the process printed before it died/timed out.
            proc.terminate()
            try:
                output, _ = proc.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                output = ""
            # Kill already-started services so we leave no half-started stack.
            for p in procs[:-1]:
                try:
                    p.terminate()
                except Exception:
                    pass
            print(
                f" {RED}FAILED{RESET}\n\n"
                f"{RED}LAUNCH ABORTED — {label.strip()} did not pass its health check "
                f"within {HEALTH_TIMEOUT_S}s.{RESET}\n"
                f"Last output from {label.strip()}:\n"
                f"{'-'*40}\n{output or '(no output)'}\n{'-'*40}\n"
                f"Check the error above, fix the problem, and re-run.\n"
            )
            sys.exit(1)

        print(f" {GREEN}healthy{RESET}  -> http://localhost:{port}/docs")

    print("\n" + "=" * 60)
    print("  All 7 services started and healthy.")
    print("  Logs will stream below.  Press Ctrl+C to stop everything.")
    print("=" * 60 + "\n")

    # ── Stream all stdout/stderr with labelled prefix ────────────────────────
    def _stream(proc: subprocess.Popen, label: str) -> None:
        tag = _tag(label)
        assert proc.stdout
        for line in proc.stdout:
            print(f"{tag} {line}", end="", flush=True)

    for (label, *_), proc in zip(SERVICES, procs):
        t = threading.Thread(target=_stream, args=(proc, label), daemon=True)
        t.start()

    # ── Wait for Ctrl+C; report unexpected exits ─────────────────────────────
    try:
        while True:
            time.sleep(1)
            for (label, *_), proc in zip(SERVICES, procs):
                if proc.poll() is not None:
                    print(
                        f"\n{RED}[{label.strip()}] CRASHED — exited with code {proc.returncode}.{RESET}\n"
                        f"The pipeline will continue running but {label.strip()} requests will fail.\n"
                        f"Restart with: python scripts/launch_backend.py\n"
                    )
    except KeyboardInterrupt:
        print("\n\nShutting down all services...")
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
    if sys.platform == "win32":
        signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    start_all()
