# backend/main.py
"""FastAPI server providing REST endpoints and SSE streaming for the agentic coding assistant."""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Ensure backend directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
load_dotenv()

from agent import request_stop, resolve_pending_approval, run_agent_loop
from llm import check_ollama_health, generate_single
from n8n_client import check_n8n_health, import_workflows_if_needed
from safety import is_sensitive_read_path, is_sensitive_write_path, resolve_safe_path, validate_command
from store import (
    create_session,
    delete_last_backup,
    delete_session,
    get_audit_logs,
    get_last_backup,
    get_messages,
    get_session,
    init_db,
    list_sessions,
    save_file_backup,
    update_session,
)
from tools import kill_proc_tree

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("backend.main")

import secrets

STARTUP_SESSION_TOKEN = secrets.token_urlsafe(32)
CORS_ORIGIN = os.environ.get("CORS_ORIGIN", "http://localhost:5173").strip()
DEFAULT_WORKSPACE = os.path.abspath(os.environ.get("WORKSPACE_DIR", "./workspace"))
BACKEND_PORT = int(os.environ.get("BACKEND_PORT", "8000"))

app = FastAPI(title="Multi-Agent Code Pipeline Backend", version="1.0.0")

allowed_origins = list(dict.fromkeys([
    CORS_ORIGIN,
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]))

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PUBLIC_PATHS = {"/health", "/models", "/auth/token", "/auth/login", "/docs", "/openapi.json", "/favicon.ico"}


@app.middleware("http")
async def verify_session_token(request: Request, call_next):
    if (
        request.method == "OPTIONS"
        or request.url.path in PUBLIC_PATHS
        or request.url.path == "/preview"
        or request.url.path.startswith("/preview/")
    ):
        return await call_next(request)

    auth_header = request.headers.get("Authorization", "").strip()
    token = ""
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    if not token:
        token = request.headers.get("X-Session-Token", "").strip()

    if not token or token != STARTUP_SESSION_TOKEN:
        return JSONResponse(
            status_code=401,
            content={"detail": "Unauthorized: invalid or missing session token."},
        )

    return await call_next(request)


@app.on_event("startup")
async def on_startup():
    logger.info("Initializing database...")
    init_db()
    os.makedirs(DEFAULT_WORKSPACE, exist_ok=True)
    logger.info(f"Default workspace ready at: {DEFAULT_WORKSPACE}")
    # Check Ollama and n8n
    ollama_ok, models = await check_ollama_health()
    logger.info(f"Ollama status: {'Connected' if ollama_ok else 'Offline'} (Models: {models})")
    n8n_ok = await check_n8n_health()
    if not n8n_ok:
        logger.info("n8n is offline; auto-starting local n8n workflow engine on port 5678...")
        try:
            import subprocess
            n8n_script = os.path.join(os.path.dirname(__file__), "n8n_server.py")
            if sys.platform == "win32":
                subprocess.Popen([sys.executable, n8n_script], creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                subprocess.Popen([sys.executable, n8n_script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(12):
                await asyncio.sleep(0.3)
                if await check_n8n_health():
                    n8n_ok = True
                    break
        except Exception as e:
            logger.warning(f"Could not auto-start local n8n server: {e}")

    logger.info(f"n8n status: {'Connected' if n8n_ok else 'Offline'}")
    if n8n_ok:
        await import_workflows_if_needed()


# ---------------------------------------------------------------------------
# Request/Response Schemas
# ---------------------------------------------------------------------------

class CreateSessionRequest(BaseModel):
    name: Optional[str] = "New Session"
    workspace_path: Optional[str] = None
    model: Optional[str] = "qwen2.5:7b-instruct-q4_K_M"
    auto_approve_writes: Optional[bool] = True


class UpdateSessionRequest(BaseModel):
    name: Optional[str] = None
    workspace_path: Optional[str] = None
    model: Optional[str] = None
    auto_approve_writes: Optional[bool] = None


class SendMessageRequest(BaseModel):
    content: str


class ApprovalRequest(BaseModel):
    action: str  # "approve" or "reject"
    auto_approve_all: Optional[bool] = False


class SaveFileRequest(BaseModel):
    path: str
    content: str
    workspace_path: Optional[str] = None


class UndoFileRequest(BaseModel):
    path: str
    workspace_path: Optional[str] = None


class InternalRunRequest(BaseModel):
    command: str
    workspace_path: Optional[str] = None


class InternalLlmRequest(BaseModel):
    prompt: str
    model: Optional[str] = "qwen2.5:7b-instruct-q4_K_M"


# ---------------------------------------------------------------------------
# Health & Status & Auth Token
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str
    password: str


VALID_ACCOUNTS = {
    "kunj": {"kunj@123", "kunj @123"},
    "parth": {"parth@123", "path@123", "path @123", "parth @123"},
    "path": {"path@123", "path @123", "parth@123", "parth @123"},
    "admin": {"admin@123", "admin @123"},
}


@app.post("/auth/login")
async def api_login(req: LoginRequest):
    uname = req.username.strip().lower()
    pwd = str(req.password).strip()
    valid_passwords = VALID_ACCOUNTS.get(uname)
    if not valid_passwords:
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    normalized_pwd = pwd.replace(" ", "")
    normalized_valids = {p.replace(" ", "") for p in valid_passwords}
    if pwd not in valid_passwords and normalized_pwd not in normalized_valids:
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    return {
        "status": "success",
        "username": uname,
        "token": STARTUP_SESSION_TOKEN,
    }


@app.get("/auth/token")
async def get_session_token():
    """Retrieve the random session token generated at backend startup."""
    return {"token": STARTUP_SESSION_TOKEN}


@app.get("/health")
async def get_health():
    ollama_ok, models = await check_ollama_health()
    n8n_ok = await check_n8n_health()
    db_ok = os.path.exists(os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "assistant.db")))
    ws_ok = os.path.isdir(DEFAULT_WORKSPACE)

    return {
        "status": "healthy" if (ollama_ok and ws_ok) else "degraded",
        "services": {
            "ollama": {"status": "ok" if ollama_ok else "offline", "models": models},
            "n8n": {"status": "ok" if n8n_ok else "offline"},
            "database": {"status": "ok" if db_ok else "error"},
            "workspace": {"status": "ok" if ws_ok else "error", "path": DEFAULT_WORKSPACE},
        },
    }


@app.get("/models")
async def get_models():
    ollama_ok, models = await check_ollama_health()
    return {"models": models, "ollama_online": ollama_ok}


@app.get("/audit")
async def list_audit_logs(session_id: Optional[str] = None, limit: int = 100):
    return {"audit_logs": get_audit_logs(session_id, limit)}


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

@app.post("/sessions")
async def api_create_session(req: CreateSessionRequest):
    ws = req.workspace_path or DEFAULT_WORKSPACE
    os.makedirs(ws, exist_ok=True)
    session = create_session(
        name=req.name or "New Session",
        workspace_path=ws,
        model=req.model or "qwen2.5:7b-instruct-q4_K_M",
        auto_approve_writes=bool(req.auto_approve_writes),
    )
    return session


@app.get("/sessions")
async def api_list_sessions():
    sessions = list_sessions()
    if not sessions:
        # Create a default session if none exists
        s = create_session(name="Initial Workspace Session", workspace_path=DEFAULT_WORKSPACE)
        sessions = [s]
    return {"sessions": sessions}


@app.get("/sessions/{session_id}")
async def api_get_session(session_id: str):
    s = get_session(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found.")
    return s


@app.patch("/sessions/{session_id}")
async def api_update_session(session_id: str, req: UpdateSessionRequest):
    s = update_session(
        session_id=session_id,
        name=req.name,
        workspace_path=req.workspace_path,
        model=req.model,
        auto_approve_writes=req.auto_approve_writes,
    )
    if not s:
        raise HTTPException(status_code=404, detail="Session not found.")
    return s


@app.delete("/sessions/{session_id}")
async def api_delete_session(session_id: str):
    success = delete_session(session_id)
    if not success:
        raise HTTPException(status_code=404, detail="Session not found.")
    return {"success": True}


@app.get("/sessions/{session_id}/messages")
async def api_get_messages(session_id: str):
    s = get_session(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found.")
    return {"messages": get_messages(session_id)}


@app.post("/sessions/{session_id}/messages")
async def api_send_message(session_id: str, req: SendMessageRequest):
    s = get_session(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found.")

    async def sse_event_stream():
        async for item in run_agent_loop(session_id=session_id, user_prompt=req.content):
            event_name = item.get("event", "message")
            data_json = json.dumps(item.get("data", {}))
            yield f"event: {event_name}\ndata: {data_json}\n\n"

    return StreamingResponse(
        sse_event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/sessions/{session_id}/stop")
async def api_stop_session(session_id: str):
    stopped = request_stop(session_id)
    return {"stopped": stopped}


# ---------------------------------------------------------------------------
# Approvals
# ---------------------------------------------------------------------------

@app.post("/approvals/{approval_id}")
async def api_resolve_approval(approval_id: str, req: ApprovalRequest):
    resolved = resolve_pending_approval(
        approval_id=approval_id,
        action=req.action,
        auto_approve_all=bool(req.auto_approve_all),
    )
    return {"resolved": resolved, "action": req.action}


# ---------------------------------------------------------------------------
# File Operations & Undo
# ---------------------------------------------------------------------------

@app.get("/files/tree")
async def api_get_files_tree(workspace_path: Optional[str] = None):
    ws = workspace_path or DEFAULT_WORKSPACE
    if not os.path.isdir(ws):
        return {"tree": []}

    ignored = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}

    def build_tree(current_dir: str, rel_prefix: str = "") -> List[Dict[str, Any]]:
        items = []
        try:
            for entry in sorted(os.scandir(current_dir), key=lambda e: (not e.is_dir(), e.name.lower())):
                if entry.name in ignored:
                    continue
                rel_path = os.path.join(rel_prefix, entry.name).replace("\\", "/")
                if entry.is_dir():
                    items.append({
                        "name": entry.name,
                        "path": rel_path,
                        "type": "directory",
                        "children": build_tree(entry.path, rel_path),
                    })
                else:
                    items.append({
                        "name": entry.name,
                        "path": rel_path,
                        "type": "file",
                        "size": entry.stat().st_size,
                    })
        except Exception:
            pass
        return items

    tree = build_tree(ws)
    return {"workspace": ws, "tree": tree}


@app.get("/files")
async def api_get_file(path: str, workspace_path: Optional[str] = None):
    ws = workspace_path or DEFAULT_WORKSPACE
    is_safe, full_p, err = resolve_safe_path(ws, path)
    if not is_safe:
        raise HTTPException(status_code=400, detail=err)

    if not os.path.exists(full_p) or not os.path.isfile(full_p):
        raise HTTPException(status_code=404, detail=f"File '{path}' not found.")

    try:
        with open(full_p, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return {"path": path, "content": content}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read file: {exc}")


@app.put("/files")
async def api_save_file(req: SaveFileRequest):
    ws = req.workspace_path or DEFAULT_WORKSPACE
    is_safe, full_p, err = resolve_safe_path(ws, req.path)
    if not is_safe:
        raise HTTPException(status_code=400, detail=err)

    if is_sensitive_write_path(req.path):
        raise HTTPException(status_code=403, detail=f"File '{req.path}' is restricted.")

    orig_content = ""
    if os.path.exists(full_p):
        try:
            with open(full_p, "r", encoding="utf-8", errors="replace") as f:
                orig_content = f.read()
        except Exception:
            pass

    try:
        os.makedirs(os.path.dirname(full_p), exist_ok=True)
        with open(full_p, "w", encoding="utf-8") as f:
            f.write(req.content)
        save_file_backup(req.path, orig_content, req.content)
        return {"success": True, "path": req.path}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {exc}")


@app.post("/files/undo")
async def api_undo_file(req: UndoFileRequest):
    ws = req.workspace_path or DEFAULT_WORKSPACE
    is_safe, full_p, err = resolve_safe_path(ws, req.path)
    if not is_safe:
        raise HTTPException(status_code=400, detail=err)

    backup = get_last_backup(req.path)
    if not backup:
        raise HTTPException(status_code=404, detail=f"No backup history found for '{req.path}'.")

    orig_content = backup["original_content"]
    try:
        if orig_content:
            with open(full_p, "w", encoding="utf-8") as f:
                f.write(orig_content)
        else:
            if os.path.exists(full_p):
                os.remove(full_p)
        delete_last_backup(backup["id"])
        return {"success": True, "path": req.path, "restored_content": orig_content}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to undo edit: {exc}")


# ---------------------------------------------------------------------------
# Internal Endpoints (for n8n workflows)
# ---------------------------------------------------------------------------

@app.post("/internal/run")
async def api_internal_run(req: InternalRunRequest):
    ws = req.workspace_path or DEFAULT_WORKSPACE
    is_valid, err, args = validate_command(req.command, ws)
    if not is_valid:
        return {"success": False, "error": err}

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=ws,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60.0)
        return {
            "success": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@app.post("/internal/llm")
async def api_internal_llm(req: InternalLlmRequest):
    summary = await generate_single(
        model=req.model or "qwen2.5:7b-instruct-q4_K_M",
        prompt=req.prompt,
        system="You are an expert software engineer generating concise commit summaries.",
    )
    return {"summary": summary}


# ---------------------------------------------------------------------------
# Project Live Preview Runner
# ---------------------------------------------------------------------------

@app.get("/preview")
@app.get("/preview/")
async def preview_project_index():
    index_file = os.path.join(DEFAULT_WORKSPACE, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)

    files = []
    if os.path.exists(DEFAULT_WORKSPACE):
        for root, _, filenames in os.walk(DEFAULT_WORKSPACE):
            for fn in filenames:
                rel = os.path.relpath(os.path.join(root, fn), DEFAULT_WORKSPACE)
                files.append(rel)

    items_html = "".join([f"<li><a href='/preview/{f}' target='_blank'>{f}</a></li>" for f in sorted(files)])
    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>MultiAgent Code - Workspace Live Preview</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #080b11; color: #f8fafc; padding: 2rem; margin: 0; }}
        .card {{ max-width: 650px; margin: 2rem auto; background: #0e1422; border: 1px solid rgba(59,130,246,0.25); border-radius: 8px; padding: 2rem; box-shadow: 0 4px 12px rgba(0,0,0,0.5); }}
        h1 {{ font-size: 1.4rem; color: #3b82f6; margin-top: 0; }}
        p {{ color: #94a3b8; font-size: 0.9rem; }}
        ul {{ list-style: none; padding: 0; }}
        li {{ margin: 0.5rem 0; padding: 0.5rem 0.75rem; background: #141c2e; border-radius: 4px; border: 1px solid rgba(255,255,255,0.05); }}
        a {{ color: #38bdf8; text-decoration: none; font-weight: 600; font-family: monospace; }}
        a:hover {{ text-decoration: underline; }}
    </style>
</head>
<body>
    <div class="card">
        <h1>MultiAgent Code - Project Live Demo</h1>
        <p>The agent built the following workspace files. Click any file to view or run:</p>
        <ul>{items_html if items_html else "<li>(No files created yet in workspace)</li>"}</ul>
    </div>
</body>
</html>"""
    return HTMLResponse(content=html_content)


app.mount("/preview", StaticFiles(directory=DEFAULT_WORKSPACE, html=True), name="preview")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=BACKEND_PORT)
