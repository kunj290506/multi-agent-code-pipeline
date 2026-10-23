#!/usr/bin/env python3
"""
start.py — Single command to start all local services for MultiAgent Code:
- Ollama model check
- Docker n8n (if available and running)
- FastAPI backend (:8000)
- React frontend (:5173)
- Health check polling
- Opens in Google Chrome / default browser
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))
PID_FILE = os.path.join(ROOT, ".pids.json")


def load_env():
    env_path = os.path.join(ROOT, ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


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


def check_ollama(model_name: str):
    print("Checking Ollama server...")
    ollama_running = False
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2) as resp:
            if resp.status == 200:
                ollama_running = True
    except Exception:
        pass

    if not ollama_running:
        print("  Starting Ollama serve in background...")
        ollama_bin = shutil.which("ollama") or "ollama"
        try:
            if sys.platform == "win32":
                subprocess.Popen([ollama_bin, "serve"], creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                subprocess.Popen([ollama_bin, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            print(f"  Warning: could not start Ollama: {e}")

        # Wait for Ollama up to 15s
        for _ in range(30):
            time.sleep(0.5)
            try:
                with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=1) as resp:
                    if resp.status == 200:
                        ollama_running = True
                        break
            except Exception:
                pass

    if ollama_running:
        print("  Ollama is running (:11434).")
        try:
            req = urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3)
            data = json.loads(req.read().decode())
            models = [m.get("name") for m in data.get("models", [])]
            if model_name not in models and not any(model_name in m for m in models):
                print(f"  Model '{model_name}' not found locally. Pulling via Ollama...")
                subprocess.run(["ollama", "pull", model_name], check=False)
            else:
                print(f"  Model '{model_name}' is ready.")
        except Exception as e:
            print(f"  Note: model check: {e}")
    else:
        print("  Warning: Ollama server not responding. Continuing with existing configuration.")


def start():
    load_env()
    model = os.environ.get("DEFAULT_MODEL", "qwen2.5-coder:3b")

    print("\n============================================================")
    print("  MULTIAGENT CODE - INITIALIZING")
    print("============================================================\n")

    # 1. Prerequisite checks
    if not shutil.which("python") and not shutil.which("python3"):
        print("Error: Python not found in PATH.")
        sys.exit(1)
    if not shutil.which("node"):
        print("Error: Node.js not found in PATH.")
        sys.exit(1)

    # 2. Ollama & model check
    check_ollama(model)

    pids = {}

    # 3. n8n check / start
    n8n_running = is_port_in_use(5678)
    if not n8n_running and shutil.which("docker"):
        try:
            dock_check = subprocess.run(["docker", "info"], capture_output=True, timeout=3)
            if dock_check.returncode == 0:
                print("Starting n8n workflow engine in Docker (:5678)...")
                subprocess.run(["docker", "compose", "up", "-d", "n8n"], cwd=ROOT, capture_output=True, timeout=15)
                for _ in range(8):
                    time.sleep(1)
                    if is_port_in_use(5678):
                        print("  n8n is running in Docker (:5678).")
                        n8n_running = True
                        break
        except Exception:
            pass

    # Fallback to local standalone n8n workflow engine
    if not n8n_running:
        print("Starting local n8n workflow engine (:5678)...")
        n8n_script = os.path.join(ROOT, "backend", "n8n_server.py")
        n8n_proc = subprocess.Popen([sys.executable, n8n_script], cwd=ROOT)
        pids["n8n"] = n8n_proc.pid
        for _ in range(10):
            time.sleep(0.5)
            if is_port_in_use(5678):
                print("  n8n local workflow engine is ready (:5678).")
                n8n_running = True
                break
    else:
        print("  n8n is active on port :5678.")

    # 4. Port cleanup
    print("Checking ports (:8000, :5173)...")
    for port in (8000, 5173):
        if is_port_in_use(port):
            print(f"  Freeing occupied port :{port}...")
            kill_port(port)
    time.sleep(1)

    # 5. Start Backend (:8000)
    print("Starting FastAPI Backend (:8000)...")
    backend_script = os.path.join(ROOT, "backend", "main.py")
    backend_proc = subprocess.Popen([sys.executable, backend_script], cwd=ROOT)
    pids["backend"] = backend_proc.pid

    # 6. Start Frontend (:5173)
    print("Starting React Frontend (:5173)...")
    frontend_dir = os.path.join(ROOT, "frontend")
    npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
    frontend_proc = subprocess.Popen([npm_cmd, "run", "dev", "--", "--port", "5173", "--host"], cwd=frontend_dir)
    pids["frontend"] = frontend_proc.pid

    # Save PIDs
    with open(PID_FILE, "w", encoding="utf-8") as f:
        json.dump(pids, f)

    # 7. Poll Backend health
    backend_ready = False
    print("Waiting for services to become healthy...")
    for _ in range(40):
        time.sleep(0.5)
        try:
            with urllib.request.urlopen("http://localhost:8000/health", timeout=1) as resp:
                if resp.status == 200:
                    backend_ready = True
                    break
        except Exception:
            pass

    if backend_ready:
        print("  Backend is healthy.")
    else:
        print("  Backend did not report healthy within timeout. Check logs.")

    # 8. Print links table
    print("\n============================================================")
    print("  ALL SERVICES RUNNING - MULTIAGENT CODE")
    print("============================================================\n")
    print("  Service           URL")
    print("  ----------------  ----------------------------------------")
    print("  Frontend UI       http://localhost:5173")
    print("  Backend API Docs  http://localhost:8000/docs")
    print("  Backend Health    http://localhost:8000/health")
    print(f"  n8n Orchestrator  {'http://localhost:5678' if n8n_running else 'Offline (Start Docker Desktop)'}")
    print("\n============================================================\n")

    # 9. Open in Google Chrome / Default Browser
    time.sleep(1)
    chrome_candidates = [
        "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
        "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
        os.path.expandvars("%LOCALAPPDATA%\\Google\\Chrome\\Application\\chrome.exe"),
    ]
    opened = False
    for path in chrome_candidates:
        if os.path.exists(path):
            try:
                subprocess.Popen([path, "http://localhost:5173"])
                opened = True
                break
            except Exception:
                pass
    if not opened:
        webbrowser.open("http://localhost:5173")

    print("Press Ctrl+C or run 'start.bat' / 'stop.bat' to stop all services.\n")
    try:
        while True:
            time.sleep(2)
            if backend_proc.poll() is not None:
                print("Backend exited unexpectedly.")
                break
            if frontend_proc.poll() is not None:
                print("Frontend exited unexpectedly.")
                break
    except KeyboardInterrupt:
        print("\nStopping services...")
        from stop import stop as stop_services
        stop_services()


if __name__ == "__main__":
    start()
