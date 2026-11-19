# backend/main.py
"""FastAPI server providing REST endpoints and SSE streaming for the agentic coding assistant."""

import asyncio
import html as html_escape
import json
import logging
import mimetypes
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

# Ensure backend directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
load_dotenv()

from agent import request_stop, resolve_pending_approval, run_agent_loop
from llm import DEFAULT_MODEL, check_ollama_health, generate_single
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
from tools import kill_proc_tree, tool_run_command
from validator import validate_workspace_file

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("backend.main")

import secrets

STARTUP_SESSION_TOKEN = secrets.token_urlsafe(32)
CORS_ORIGIN = os.environ.get("CORS_ORIGIN", "http://localhost:5173").strip()
DEFAULT_WORKSPACE = os.path.abspath(os.environ.get("WORKSPACE_DIR", "./workspace"))
BACKEND_PORT = int(os.environ.get("BACKEND_PORT", "8000"))

app = FastAPI(title="Multi-Agent Code Pipeline Backend", version="1.0.0")

ALLOW_ORIGIN_REGEX = (
    r"^https?://("
    r"localhost|"
    r"127\.0\.0\.1|"
    r"10(?:\.\d{1,3}){3}|"
    r"192\.168(?:\.\d{1,3}){2}|"
    r"172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}"
    r")(:\d+)?$"
)
allowed_origins = [CORS_ORIGIN] if CORS_ORIGIN else []

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=ALLOW_ORIGIN_REGEX,
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
        logger.info("n8n is offline on port 5678 (Ready for Docker n8n container: docker compose up -d n8n)")
    else:
        logger.info("n8n status: Connected on port 5678")
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


def clear_workspace_directory(workspace_path: str = DEFAULT_WORKSPACE):
    """Clean all files and subdirectories from workspace so it starts completely empty."""
    if os.path.exists(workspace_path):
        for item in os.listdir(workspace_path):
            item_path = os.path.join(workspace_path, item)
            try:
                if os.path.isdir(item_path):
                    shutil.rmtree(item_path, ignore_errors=True)
                else:
                    os.remove(item_path)
            except Exception as e:
                logger.warning(f"Error removing {item_path}: {e}")
    os.makedirs(workspace_path, exist_ok=True)


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

    # Clean workspace directory by default on login so it starts fresh and empty
    clear_workspace_directory(DEFAULT_WORKSPACE)
    logger.info(f"User '{uname}' logged in. Workspace cleared to clean empty state.")

    return {
        "status": "success",
        "username": uname,
        "token": STARTUP_SESSION_TOKEN,
    }


@app.post("/workspace/clear")
async def api_clear_workspace(workspace_path: Optional[str] = None):
    ws = workspace_path or DEFAULT_WORKSPACE
    clear_workspace_directory(ws)
    return {"status": "success", "message": "Workspace cleared successfully.", "workspace": ws}


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
    if "qwen2.5-coder:3b" in models:
        default_model = "qwen2.5-coder:3b"
    elif DEFAULT_MODEL in models:
        default_model = DEFAULT_MODEL
    else:
        default_model = models[0] if models else DEFAULT_MODEL
    return {"models": models, "default_model": default_model, "ollama_online": ollama_ok}


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
            "Cache-Control": "no-cache, no-transform",
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
# Project Live Preview & Interactive Runner
# ---------------------------------------------------------------------------

NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}

PREVIEW_RUNTIME_BRIDGE = """<script data-multiagent-bridge="true">
(function() {
  if (window.__maBridgeInstalled) return;
  window.__maBridgeInstalled = true;
  function send(type, payload) {
    try {
      if (window.parent && window.parent !== window) {
        window.parent.postMessage(Object.assign({ source: 'multiagent-preview', type: type, ts: Date.now() }, payload), '*');
      }
    } catch (e) {}
  }
  function stringifyArg(a) {
    if (a instanceof Error) return a.stack || a.message || String(a);
    if (typeof a === 'object' && a !== null) {
      try { return JSON.stringify(a); } catch (e) { return String(a); }
    }
    return String(a);
  }
  ['log', 'warn', 'error'].forEach(function(level) {
    var orig = console[level];
    console[level] = function() {
      var args = Array.prototype.slice.call(arguments);
      send(level, { message: args.map(stringifyArg).join(' ') });
      if (orig) return orig.apply(console, arguments);
    };
  });
  window.addEventListener('error', function(ev) {
    var msg = ev.message || 'Runtime script error';
    if (ev.lineno) msg += ' (line ' + ev.lineno + (ev.colno ? ':' + ev.colno : '') + ')';
    send('error', { message: msg });
  });
  window.addEventListener('unhandledrejection', function(ev) {
    var reason = ev.reason ? stringifyArg(ev.reason) : 'Unhandled promise rejection';
    send('error', { message: 'Unhandled Promise Rejection: ' + reason });
  });
  window.addEventListener('DOMContentLoaded', function() {
    send('ready', { title: document.title || '' });
  });
})();
</script>"""


def detect_workspace_preview(workspace_path: str = DEFAULT_WORKSPACE) -> Dict[str, Any]:
    """Inspect workspace files and determine the best preview/run mode for any project type."""
    ignored = {".git", "node_modules", "__pycache__", ".venv", "venv"}
    files: List[str] = []
    if os.path.isdir(workspace_path):
        for root, dirs, filenames in os.walk(workspace_path):
            dirs[:] = [d for d in dirs if d not in ignored]
            for fn in filenames:
                rel = os.path.relpath(os.path.join(root, fn), workspace_path).replace("\\", "/")
                files.append(rel)
    files.sort()

    if not files:
        return {
            "type": "empty",
            "entry": None,
            "preview_url": "/preview/",
            "command": None,
            "html_files": [],
            "files": [],
            "validation": {"valid": True, "errors": [], "warnings": []},
        }

    html_files = [f for f in files if f.lower().endswith((".html", ".htm"))]
    if html_files:
        # Priority: root index.html -> root *.html -> dist/public/src index.html -> any index.html -> first *.html
        def html_rank(p: str) -> tuple:
            low = p.lower()
            depth = low.count("/")
            if low == "index.html":
                return (0, 0, low)
            if depth == 0:
                return (1, 0, low)
            if low in ("dist/index.html", "build/index.html", "public/index.html", "src/index.html"):
                return (2, depth, low)
            if os.path.basename(low) == "index.html":
                return (3, depth, low)
            return (4, depth, low)

        html_files_sorted = sorted(html_files, key=html_rank)
        entry = html_files_sorted[0]
        val = validate_workspace_file(workspace_path, entry, check_missing_assets=True, strict_assets=True)
        return {
            "type": "web",
            "entry": entry,
            "preview_url": f"/preview/{entry}",
            "command": None,
            "html_files": html_files_sorted,
            "files": files,
            "validation": val,
        }

    py_files = [f for f in files if f.lower().endswith(".py")]
    if py_files:
        def py_rank(p: str) -> tuple:
            base = os.path.basename(p).lower()
            is_test = base.startswith("test_") or base.endswith("_test.py")
            priority = {"main.py": 0, "app.py": 1, "hello.py": 2, "run.py": 3, "index.py": 4}.get(base, 5)
            return (1 if is_test else 0, p.count("/"), priority, p.lower())

        entry = sorted(py_files, key=py_rank)[0]
        val = validate_workspace_file(workspace_path, entry)
        return {
            "type": "python",
            "entry": entry,
            "preview_url": "/preview/",
            "command": f"python {entry}",
            "html_files": [],
            "files": files,
            "validation": val,
        }

    js_files = [f for f in files if f.lower().endswith((".js", ".mjs"))]
    if js_files:
        def js_rank(p: str) -> tuple:
            base = os.path.basename(p).lower()
            priority = {"index.js": 0, "main.js": 1, "app.js": 2, "server.js": 3}.get(base, 4)
            return (p.count("/"), priority, p.lower())

        entry = sorted(js_files, key=js_rank)[0]
        val = validate_workspace_file(workspace_path, entry)
        return {
            "type": "node",
            "entry": entry,
            "preview_url": "/preview/",
            "command": f"node {entry}",
            "html_files": [],
            "files": files,
            "validation": val,
        }

    return {
        "type": "files",
        "entry": files[0],
        "preview_url": f"/preview/{files[0]}",
        "command": None,
        "html_files": [],
        "files": files,
        "validation": {"valid": True, "errors": [], "warnings": []},
    }


def _prepare_preview_html(raw_html: str, rel_entry: str, workspace_path: str) -> str:
    """
    Prepare HTML for reliable live preview serving:
    1. Rewrite root-relative local asset URLs (href="/style.css" -> href="/preview/style.css")
       when the referenced file exists in the workspace.
    2. Inject <base href="/preview/<subdir>/"> if missing so relative links work from any route.
    3. Inject lightweight non-destructive console/error postMessage bridge for the Studio Preview tab.
    """
    entry_dir = os.path.dirname(rel_entry.replace("\\", "/")).strip("/")
    base_href = f"/preview/{entry_dir}/" if entry_dir else "/preview/"

    # Rewrite root-relative asset references (e.g. href="/style.css", src="/app.js") if file exists in workspace
    def rewrite_root_attr(match: re.Match) -> str:
        attr_name = match.group(1)
        quote = match.group(2)
        target = match.group(3)
        # Skip already-prefixed /preview/, protocol-relative //, or empty
        if target.startswith("/preview/") or target.startswith("//") or target == "/":
            return match.group(0)
        rel_candidate = target.lstrip("/").split("?")[0].split("#")[0]
        if rel_candidate:
            is_safe, full_p, _ = resolve_safe_path(workspace_path, rel_candidate)
            if is_safe and os.path.isfile(full_p):
                return f"{attr_name}={quote}/preview/{target.lstrip('/')}{quote}"
        return match.group(0)

    processed = re.sub(
        r"""\b(href|src)\s*=\s*(["'])(/[^"']+)\2""",
        rewrite_root_attr,
        raw_html,
        flags=re.IGNORECASE,
    )

    has_base = bool(re.search(r"<base\b", processed, re.IGNORECASE))
    injection = ("" if has_base else f'<base href="{base_href}">\n') + PREVIEW_RUNTIME_BRIDGE

    head_open = re.search(r"<head[^>]*>", processed, re.IGNORECASE)
    if head_open:
        insert_pos = head_open.end()
        return processed[:insert_pos] + "\n" + injection + "\n" + processed[insert_pos:]

    html_open = re.search(r"<html[^>]*>", processed, re.IGNORECASE)
    if html_open:
        insert_pos = html_open.end()
        return processed[:insert_pos] + "\n<head>\n" + injection + "\n</head>\n" + processed[insert_pos:]

    return injection + "\n" + processed


class WorkspaceRunRequest(BaseModel):
    command: Optional[str] = None
    entry: Optional[str] = None
    workspace_path: Optional[str] = None


@app.post("/workspace/run")
async def api_workspace_run(req: WorkspaceRunRequest):
    """Run a detected or specified Python/Node script inside the workspace sandbox for live demo output."""
    ws = req.workspace_path or DEFAULT_WORKSPACE
    cmd = (req.command or "").strip()
    if not cmd:
        if req.entry:
            entry_clean = req.entry.replace("\\", "/").lstrip("/")
            ext = os.path.splitext(entry_clean)[1].lower()
            if ext == ".py":
                cmd = f"python {entry_clean}"
            elif ext in (".js", ".mjs"):
                cmd = f"node {entry_clean}"
            else:
                raise HTTPException(status_code=400, detail=f"Unsupported runnable file type: {entry_clean}")
        else:
            info = detect_workspace_preview(ws)
            cmd = info.get("command") or ""
            if not cmd:
                raise HTTPException(status_code=400, detail="No runnable Python or Node script found in workspace.")

    success, wrapped_out, extra = await tool_run_command(
        workspace_root=ws,
        command=cmd,
        timeout_seconds=20,
    )
    return {
        "success": success,
        "command": cmd,
        "returncode": extra.get("returncode", 0 if success else 1),
        "output": extra.get("output", wrapped_out),
    }


@app.get("/preview/info")
async def preview_project_info(workspace_path: Optional[str] = None):
    """Return detected project type, entry point, preview URL, and validation status."""
    ws = workspace_path or DEFAULT_WORKSPACE
    return detect_workspace_preview(ws)


@app.get("/preview")
@app.get("/preview/")
async def preview_project_index():
    info = detect_workspace_preview(DEFAULT_WORKSPACE)
    if info["type"] == "web" and info["entry"]:
        entry_rel = info["entry"]
        is_safe, full_p, _ = resolve_safe_path(DEFAULT_WORKSPACE, entry_rel)
        if is_safe and os.path.isfile(full_p):
            with open(full_p, "r", encoding="utf-8", errors="replace") as f:
                raw_html = f.read()
            rendered = _prepare_preview_html(raw_html, entry_rel, DEFAULT_WORKSPACE)
            return HTMLResponse(content=rendered, headers=NO_CACHE_HEADERS)

    files = info.get("files", [])
    items_html = "".join(
        f'<li><a href="/preview/{html_escape.escape(f)}">{html_escape.escape(f)}</a></li>'
        for f in files
    )
    subtitle = (
        f'Detected runnable {info["type"].capitalize()} entry: <code>{html_escape.escape(info["entry"])}</code>. '
        "Use the Studio Preview tab to execute it live, or inspect any workspace file below:"
        if info["type"] in ("python", "node") and info.get("entry")
        else "Workspace files:"
    )
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>MultiAgent Code — Workspace Preview</title>
    <style>
        body {{ font-family: system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif; background: #FAFAF8; color: #1F2328; padding: 2rem; margin: 0; }}
        .card {{ max-width: 640px; margin: 2rem auto; background: #FFFFFF; border: 1px solid #E5E3DD; border-radius: 8px; padding: 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }}
        h1 {{ font-size: 18px; color: #1F2328; margin: 0 0 8px 0; }}
        p {{ color: #667085; font-size: 14px; margin: 0 0 16px 0; line-height: 1.5; }}
        code {{ background: #F3F2EE; padding: 2px 6px; border-radius: 4px; font-family: ui-monospace, Consolas, monospace; color: #0E7C86; }}
        ul {{ list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 8px; }}
        li {{ padding: 10px 12px; background: #FAFAF8; border-radius: 6px; border: 1px solid #E5E3DD; }}
        a {{ color: #0E7C86; text-decoration: none; font-weight: 500; font-family: ui-monospace, Consolas, monospace; font-size: 13px; }}
        a:hover {{ text-decoration: underline; }}
    </style>
</head>
<body>
    <div class="card">
        <h1>MultiAgent Code — Live Preview</h1>
        <p>{subtitle}</p>
        <ul>{items_html if items_html else "<li>No files created yet in workspace. Ask the assistant to build a project.</li>"}</ul>
    </div>
</body>
</html>"""
    return HTMLResponse(content=html_content, headers=NO_CACHE_HEADERS)


@app.get("/preview/{file_path:path}")
async def preview_project_asset(file_path: str):
    """Serve any workspace file under /preview/ with no-cache headers, safe sandboxing, and HTML bridge."""
    clean_rel = file_path.replace("\\", "/").lstrip("/")
    is_safe, full_p, err = resolve_safe_path(DEFAULT_WORKSPACE, clean_rel)
    if not is_safe:
        raise HTTPException(status_code=403, detail=err)

    # Support directory URLs like /preview/subdir/ -> /preview/subdir/index.html
    if os.path.isdir(full_p):
        dir_index = os.path.join(full_p, "index.html")
        if os.path.isfile(dir_index):
            full_p = dir_index
            clean_rel = f"{clean_rel.rstrip('/')}/index.html" if clean_rel else "index.html"
        else:
            raise HTTPException(status_code=404, detail="Directory index not found.")

    if not os.path.isfile(full_p):
        raise HTTPException(status_code=404, detail=f"Preview asset '{clean_rel}' not found.")

    ext = os.path.splitext(full_p)[1].lower()
    if ext in (".html", ".htm"):
        with open(full_p, "r", encoding="utf-8", errors="replace") as f:
            raw_html = f.read()
        rendered = _prepare_preview_html(raw_html, clean_rel, DEFAULT_WORKSPACE)
        return HTMLResponse(content=rendered, headers=NO_CACHE_HEADERS)

    mime_type, _ = mimetypes.guess_type(full_p)
    if ext == ".js" or ext == ".mjs":
        mime_type = "application/javascript; charset=utf-8"
    elif ext == ".css":
        mime_type = "text/css; charset=utf-8"
    elif ext == ".svg":
        mime_type = "image/svg+xml"

    return FileResponse(full_p, media_type=mime_type, headers=NO_CACHE_HEADERS)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=BACKEND_PORT)
