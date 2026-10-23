#!/usr/bin/env python3
"""
stop.py — Cleanly stop all running services and free ports.
"""

import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
PID_FILE = os.path.join(ROOT, ".pids.json")


def kill_pid(pid: int):
    try:
        if sys.platform == "win32":
            subprocess.run(f"taskkill /F /T /PID {pid}", shell=True, capture_output=True)
        else:
            subprocess.run(["kill", "-9", str(pid)], capture_output=True)
    except Exception:
        pass


def kill_port(port: int):
    try:
        if sys.platform == "win32":
            out = subprocess.check_output(f"netstat -ano | findstr :{port}", shell=True, text=True, stderr=subprocess.DEVNULL)
            for line in out.splitlines():
                if "LISTENING" in line:
                    parts = line.strip().split()
                    pid = parts[-1]
                    if pid and pid != "0":
                        subprocess.run(f"taskkill /F /PID {pid}", shell=True, capture_output=True)
        else:
            out = subprocess.check_output(["lsof", "-ti", f":{port}"], text=True, stderr=subprocess.DEVNULL)
            for pid in out.splitlines():
                if pid:
                    subprocess.run(["kill", "-9", pid], capture_output=True)
    except Exception:
        pass


def stop():
    print("\nStopping MultiAgent Code services...")

    # Read and kill saved PIDs
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r", encoding="utf-8") as f:
                pids = json.load(f)
            for name, pid in pids.items():
                print(f"  Stopping {name} (PID {pid})...")
                kill_pid(pid)
            os.remove(PID_FILE)
        except Exception as e:
            print(f"  Note while stopping PIDs: {e}")

    # Ensure ports are free
    for port in (8000, 5173, 5678):
        kill_port(port)

    # Stop Docker n8n if running
    if shutil.which("docker"):
        try:
            subprocess.run(["docker", "compose", "stop", "n8n"], cwd=ROOT, capture_output=True, timeout=5)
        except Exception:
            pass

    time.sleep(1)
    print("All services stopped successfully.\n")


if __name__ == "__main__":
    stop()
