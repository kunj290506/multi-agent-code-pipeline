"""
Webapp Backend -- Orchestration Layer.

A thin FastAPI backend that drives the multi-agent pipeline by calling each
agent's API in sequence.  Exposes:

  POST /runs                        — start a new pipeline run
  GET  /runs/{request_id}/status    — poll the live state of a run in progress
  GET  /runs/{request_id}/events    — SSE stream of live step events
  POST /runs/{request_id}/cancel    — request cancellation of an in-flight run
  GET  /logs                        — list completed run log files
  GET  /logs/{request_id}           — full log JSON for one run
  GET  /history                     — in-memory run history list
  GET  /files                       — target-app/ directory tree
  GET  /file?path=                  — read a file inside target-app/
  GET  /health                      — service health
  WS   /ws                          — legacy WebSocket feed (kept for compat)

NOTE: POST /request is kept as an alias for POST /runs for backwards compat
with the old frontend.

Live-state design
-----------------
  run_states   : dict[request_id, RunState]   — updated immediately after
                  each agent call returns; read by /status and /events.
  cancel_flags : dict[request_id, bool]       — set True by /cancel; checked
                  at each step boundary before the next agent is dispatched.

A step already mid-call (e.g. an in-flight Ollama request) will finish that
call before the cancellation takes effect — we do not hard-kill in-flight
HTTP requests.
"""

import asyncio
import json
import logging
import os
import shutil
import signal as _signal
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

import httpx
import auth
from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("webapp-backend")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TARGET_APP_DIR: str = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "target-app")
)

LOGS_DIR: str = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "logs")
)

# Project workspaces root: each named project gets its own sub-directory here.
PROJECTS_DIR: str = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "projects")
)

AGENT_URLS: dict[str, str] = {
    "planner-agent": "http://localhost:8010/plan",
    "rag-agent": "http://localhost:8011/query",
    "db-agent": "http://localhost:8012/generate",
    "db-executor": "http://localhost:8013/execute",
    "codegen-agent": "http://localhost:8014/generate",
    "reviewer-agent": "http://localhost:8015/review",
}

# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Webapp Orchestrator API",
    description=(
        "Thin orchestration layer that calls the multi-agent pipeline "
        "and streams results over WebSockets and SSE."
    ),
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)


@app.on_event("startup")
def _startup() -> None:
    """Initialise the auth users DB on server startup."""
    auth.init_db()

# ---------------------------------------------------------------------------
# In-memory stores
# ---------------------------------------------------------------------------

# Legacy run history list (kept for /history compatibility).
run_history: list[dict[str, Any]] = []

# Live state keyed by request_id.  Updated immediately after each agent call.
# Shape mirrors the log schema so /status and the final log file are consistent.
run_states: dict[str, dict[str, Any]] = {}

# Cancellation flags.  Set to True by POST /runs/{id}/cancel.
# Checked at each step boundary before dispatching the next agent.
cancel_flags: dict[str, bool] = {}

# Per-run SSE event queues: request_id -> asyncio.Queue of dicts.
# Each dict is a raw event payload; None sentinel closes the stream.
sse_queues: dict[str, asyncio.Queue] = {}

# Running project processes: project_id -> {pid, port, url, type, process}
running_processes: dict[str, dict[str, Any]] = {}

# ---------------------------------------------------------------------------
# WebSocket management (legacy, kept for backwards compat)
# ---------------------------------------------------------------------------

active_connections: list[WebSocket] = []


# NOTE: /ws is intentionally left unprotected — WebSockets cannot reliably
# send HttpOnly cookies in all browsers without additional handshake logic.
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Accept a WebSocket connection for real-time pipeline updates."""
    await websocket.accept()
    active_connections.append(websocket)
    logger.info("WebSocket client connected. Total: %d", len(active_connections))
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        active_connections.remove(websocket)
        logger.info("WebSocket client disconnected. Total: %d", len(active_connections))


async def broadcast(message: dict) -> None:
    """Send a JSON message to all connected WebSocket clients."""
    disconnected: list[WebSocket] = []
    for connection in active_connections:
        try:
            await connection.send_json(message)
        except Exception:
            disconnected.append(connection)
    for conn in disconnected:
        if conn in active_connections:
            active_connections.remove(conn)


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------

async def _sse_push(request_id: str, event: dict) -> None:
    """Push an event to the SSE queue for request_id (if one exists)."""
    q = sse_queues.get(request_id)
    if q is not None:
        await q.put(event)


async def _sse_close(request_id: str) -> None:
    """Send the None sentinel to close the SSE stream."""
    q = sse_queues.get(request_id)
    if q is not None:
        await q.put(None)


def _sse_format(data: dict) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(data, default=str)}\n\n"


# ---------------------------------------------------------------------------
# Live-state helpers
# ---------------------------------------------------------------------------

def _init_run_state(request_id: str, feature_request: str, workspace_dir: str | None = None) -> dict:
    """Create and register the initial live state for a new run.

    workspace_dir: absolute path to the project workspace for this run.
    If None, uses the default target-app/ directory.
    """
    state: dict[str, Any] = {
        "request_id": request_id,
        "feature_request": feature_request,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
        "status": "running",
        "total_duration_ms": None,
        "steps": [],
        # Workspace dir this run writes files into (None = default target-app/)
        "workspace_dir": workspace_dir,
    }
    run_states[request_id] = state
    cancel_flags[request_id] = False
    sse_queues[request_id] = asyncio.Queue()
    return state


def _step_record(
    agent: str,
    status: str,
    *,
    attempt_number: int = 1,
    input_summary: str = "",
    output_summary: str = "",
    verdict: str | None = None,
    severity_counts: dict | None = None,
    duration_ms: int | None = None,
    data: dict | None = None,
) -> dict:
    """Build a normalised step record."""
    return {
        "agent": agent,
        "status": status,
        "attempt_number": attempt_number,
        "input_summary": input_summary,
        "output_summary": output_summary,
        "verdict": verdict,
        "severity_counts": severity_counts or {},
        "duration_ms": duration_ms,
        # Full raw output, present for live polling and final log.
        "data": data or {},
    }


async def _push_step(request_id: str, step: dict) -> None:
    """Append a completed step to the run state and push an SSE event."""
    state = run_states.get(request_id)
    if state is not None:
        state["steps"].append(step)
    event = {"type": "step", "request_id": request_id, "step": step}
    await _sse_push(request_id, event)
    await broadcast({**event})


async def _finalize_run(request_id: str, status: str) -> None:
    """Mark a run complete, compute total_duration_ms, write log, push SSE close.

    If the run has a project workspace and status is 'success', also pushes a
    'project_ready' SSE event so the frontend can trigger auto-run/preview.
    """
    state = run_states.get(request_id)
    if state is None:
        return
    started = datetime.fromisoformat(state["started_at"])
    completed = datetime.now(timezone.utc)
    state["completed_at"] = completed.isoformat()
    state["status"] = status
    state["total_duration_ms"] = int((completed - started).total_seconds() * 1000)
    _write_run_log(state)
    # Update legacy run_history entry if present.
    for rec in run_history:
        if rec.get("request_id") == request_id:
            rec.update(state)
            break
    await _sse_push(request_id, {
        "type": "done",
        "request_id": request_id,
        "status": status,
        "total_duration_ms": state["total_duration_ms"],
    })
    # If this was a named project run that succeeded, tell the frontend it's ready to run.
    if status == "success" and state.get("workspace_dir"):
        await _sse_push(request_id, {
            "type": "project_ready",
            "request_id": request_id,
            "workspace_dir": state["workspace_dir"],
        })
        await broadcast({
            "type": "project_ready",
            "request_id": request_id,
            "workspace_dir": state["workspace_dir"],
        })
    await _sse_close(request_id)
    await broadcast({"type": "done", "request_id": request_id, "status": status})


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class RunRequest(BaseModel):
    """Request body for POST /runs (and POST /request alias)."""
    request: str = Field(..., min_length=1, description="Feature request in plain language.")
    project_name: str | None = Field(
        default=None,
        description=(
            "Optional project name.  When provided, the pipeline creates a fresh "
            "workspace directory under projects/{project_name}_{request_id}/ and "
            "writes all generated files there instead of the default target-app/."
        ),
    )

# Alias kept for backwards compat.
FeatureRequest = RunRequest


# ---------------------------------------------------------------------------
# Agent communication
# ---------------------------------------------------------------------------

async def call_agent(agent_name: str, payload: dict) -> dict:
    """Call a downstream agent API and return the JSON response."""
    url = AGENT_URLS.get(agent_name)
    if not url:
        raise ValueError(f"Unknown agent: {agent_name}")
    async with httpx.AsyncClient(timeout=300) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        return response.json()


# ---------------------------------------------------------------------------
# Core endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health_check() -> dict:
    """Return service health status."""
    return {"status": "healthy", "service": "webapp-backend"}


@app.get("/history")
def get_history(current_user: dict = Depends(auth.get_current_user)) -> list[dict]:
    """Return the list of past pipeline runs (in-memory)."""
    return run_history


# ---------------------------------------------------------------------------
# Live-run endpoints
# ---------------------------------------------------------------------------

@app.post("/runs", status_code=202)
async def start_run(req: RunRequest, current_user: dict = Depends(auth.get_current_user)) -> dict:
    """Start a new pipeline run and return immediately with the request_id.

    The pipeline executes asynchronously.  Poll GET /runs/{id}/status or
    stream GET /runs/{id}/events to observe progress.

    If req.project_name is set, a fresh workspace directory is created under
    projects/{safe_name}_{request_id}/ and used instead of the default target-app/.
    """
    request_id = os.urandom(4).hex()

    # Resolve workspace directory.
    workspace_dir: str | None = None
    if req.project_name:
        # Sanitise project name: keep alphanumeric, hyphens, underscores only.
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in req.project_name)
        workspace_dir = os.path.join(PROJECTS_DIR, f"{safe_name}_{request_id}")
        os.makedirs(workspace_dir, exist_ok=True)
        logger.info("Created project workspace: %s", workspace_dir)

    state = _init_run_state(request_id, req.request, workspace_dir=workspace_dir)
    run_history.append(state)
    # Fire the pipeline as a background task so this endpoint returns immediately.
    asyncio.create_task(_run_pipeline(request_id, req.request))
    await broadcast({"type": "start", "request_id": request_id, "request": req.request})
    return {
        "request_id": request_id,
        "status": "accepted",
        "workspace_dir": workspace_dir,
    }


@app.post("/runs/{request_id}/cancel")
async def cancel_run(request_id: str, current_user: dict = Depends(auth.get_current_user)) -> dict:
    """Request cancellation of an in-flight run.

    Sets a cancellation flag that is checked at each step boundary before the
    next agent is dispatched.  A step already mid-call will finish that call
    before the cancellation takes effect — we do not hard-kill in-flight HTTP
    requests.
    """
    if request_id not in run_states:
        raise HTTPException(status_code=404, detail=f"Run {request_id} not found.")
    state = run_states[request_id]
    if state["status"] != "running":
        return {"request_id": request_id, "status": state["status"], "message": "Run is not active."}
    cancel_flags[request_id] = True
    logger.info("Cancellation requested for run %s", request_id)
    return {"request_id": request_id, "status": "cancellation_requested"}


@app.get("/runs/{request_id}/status")
def get_run_status(request_id: str, current_user: dict = Depends(auth.get_current_user)) -> dict:
    """Return the current live state of a run (poll at ~1–2 s intervals).

    Returns a full snapshot: status, steps so far (each with real agent
    output), and timing.  Steps not yet reached show as absent from the list —
    this endpoint never returns invented or placeholder data.
    """
    state = run_states.get(request_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Run {request_id} not found.")
    return state


@app.get("/runs/{request_id}/events")
async def run_events(request_id: str, current_user: dict = Depends(auth.get_current_user)) -> StreamingResponse:
    """SSE stream of live step events for a run.

    Each event is a JSON-encoded dict with a 'type' field:
      - 'step'  : a step completed; carries full step data
      - 'done'  : pipeline finished; carries final status + duration_ms

    If the run has already completed, sends the stored steps then closes.
    """
    # If the run finished before the client connected, replay from state.
    state = run_states.get(request_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Run {request_id} not found.")

    async def _event_stream() -> AsyncGenerator[str, None]:
        # If finished, replay completed steps and return.
        if state["status"] not in ("running",):
            for step in state.get("steps", []):
                yield _sse_format({"type": "step", "request_id": request_id, "step": step})
            yield _sse_format({
                "type": "done",
                "request_id": request_id,
                "status": state["status"],
                "total_duration_ms": state.get("total_duration_ms"),
            })
            return
        # Otherwise stream from the live queue.
        q = sse_queues.get(request_id)
        if q is None:
            return
        while True:
            event = await q.get()
            if event is None:
                break
            yield _sse_format(event)

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Backwards-compat alias: POST /request → same as POST /runs
# ---------------------------------------------------------------------------

@app.post("/request")
async def process_request_alias(req: RunRequest) -> dict:
    """Backwards-compatible alias for POST /runs.  Returns {status: 'success'}
    after the pipeline completes (blocking, for old frontend compatibility)."""
    request_id = os.urandom(4).hex()
    state = _init_run_state(request_id, req.request)
    run_history.append(state)
    await broadcast({"type": "start", "request_id": request_id, "request": req.request})
    await _run_pipeline(request_id, req.request)
    return {"status": run_states.get(request_id, {}).get("status", "success"), "request_id": request_id}


# ---------------------------------------------------------------------------
# Log endpoints
# ---------------------------------------------------------------------------

@app.get("/logs")
def list_logs() -> list[dict]:
    """Return metadata for all pipeline run log files.

    Intentionally unauthenticated — run logs are read-only historical records
    with no sensitive user data.  The eval harness (run_eval.py) reads this
    endpoint without credentials; all write endpoints remain protected.
    """
    if not os.path.exists(LOGS_DIR):
        return []
    result = []
    for filename in sorted(os.listdir(LOGS_DIR)):
        if not filename.endswith(".json"):
            continue
        path = os.path.join(LOGS_DIR, filename)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            result.append({
                "filename": filename,
                "request_id": data.get("request_id"),
                "feature_request": data.get("feature_request") or data.get("request"),
                "overall_status": data.get("status") or data.get("overall_status"),
                "total_duration_ms": data.get("total_duration_ms"),
                "started_at": data.get("started_at"),
                "completed_at": data.get("completed_at"),
                "retry_count": sum(
                    1 for s in data.get("steps", [])
                    if s.get("attempt_number", 1) > 1
                ),
            })
        except Exception as exc:
            logger.warning("Could not read log file %s: %s", filename, exc)
    return result


@app.get("/logs/{request_id}")
def get_log(request_id: str) -> dict:
    """Return the full log JSON for a specific pipeline run.

    Intentionally unauthenticated — same rationale as GET /logs.
    """
    if not os.path.exists(LOGS_DIR):
        raise HTTPException(status_code=404, detail="No logs directory found.")
    for filename in os.listdir(LOGS_DIR):
        if filename.startswith(f"run_{request_id}_") and filename.endswith(".json"):
            path = os.path.join(LOGS_DIR, filename)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    return json.load(fh)
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc)) from exc
    raise HTTPException(status_code=404, detail=f"No log found for request_id={request_id}")


# ---------------------------------------------------------------------------
# Pipeline execution
# ---------------------------------------------------------------------------

async def _run_pipeline(request_id: str, feature_request: str) -> None:
    """Execute the full five-agent pipeline for a given request.

    Updates run_states[request_id] in real time after each agent call.
    Checks cancel_flags[request_id] at each step boundary.
    """
    state = run_states[request_id]

    async def _is_cancelled() -> bool:
        return cancel_flags.get(request_id, False)

    # -- Step 1: Planner -------------------------------------------------------
    await broadcast({"type": "log", "agent": "Planner", "message": "Planning tasks...", "request_id": request_id})
    try:
        t0 = time.monotonic()
        plan = await call_agent(
            "planner-agent",
            {"feature_request": feature_request, "offline": True},
        )
        dur = int((time.monotonic() - t0) * 1000)
        if "subtasks" not in plan:
            raise ValueError(
                f"Planner returned invalid output: missing 'subtasks' key. Got: {list(plan.keys())}"
            )
        subtask_summary = f"{len(plan['subtasks'])} subtasks: " + ", ".join(
            f"{s['agent']}({s['task_id']})" for s in plan["subtasks"]
        )
        step = _step_record(
            "planner-agent", "done",
            input_summary=feature_request[:200],
            output_summary=subtask_summary,
            duration_ms=dur,
            data=plan,
        )
        await _push_step(request_id, step)
        await broadcast({"type": "log", "agent": "Planner", "message": "Plan generated.", "data": plan})
    except Exception as exc:
        logger.error("Planner failed: %s", exc)
        step = _step_record("planner-agent", "failed", output_summary=str(exc))
        await _push_step(request_id, step)
        await broadcast({"type": "log", "agent": "Planner", "message": f"Planner failed: {exc}", "status": "error"})
        await _finalize_run(request_id, "error")
        return

    subtasks = plan.get("subtasks", [])
    context_str = ""
    last_codegen_artifact: dict | None = None
    # Workspace directory for this run (project-scoped or default target-app/).
    workspace = _get_workspace(request_id)

    # -- Step 2: Execute subtasks ----------------------------------------------
    for task in subtasks:
        # Check for cancellation before dispatching each agent.
        if await _is_cancelled():
            logger.info("Run %s cancelled before agent %s", request_id, task["agent"])
            cancel_step = _step_record(
                task["agent"], "cancelled",
                input_summary=task.get("description", "")[:200],
                output_summary="Cancelled before dispatch.",
            )
            await _push_step(request_id, cancel_step)
            await _finalize_run(request_id, "cancelled")
            return

        agent = task["agent"]
        desc = task["description"]
        await broadcast({"type": "log", "agent": agent, "message": f"Executing: {desc}", "request_id": request_id})

        try:
            if agent == "system":
                await _handle_system_task(desc, workspace=workspace)
                step = _step_record("system", "done", input_summary=desc)
                await _push_step(request_id, step)

            elif agent == "rag-agent":
                t0 = time.monotonic()
                res = await call_agent("rag-agent", {"description": desc, "top_k": 5})
                dur = int((time.monotonic() - t0) * 1000)
                if "answer" not in res:
                    raise ValueError(
                        f"RAG agent returned invalid output: missing 'answer' key. Got: {list(res.keys())}"
                    )
                context_str += f"\nRAG Context: {res.get('answer', '')}"
                confidence = res.get("confidence", 0.0)
                low_conf = res.get("low_confidence", True)
                summary = (
                    f"confidence={confidence:.2f}"
                    + (" [LOW CONFIDENCE]" if low_conf else "")
                    + f" — {res.get('answer','')[:120]}"
                )
                step = _step_record(
                    "rag-agent", "done",
                    input_summary=desc[:200],
                    output_summary=summary,
                    duration_ms=dur,
                    data=res,
                )
                await _push_step(request_id, step)
                await broadcast({"type": "log", "agent": agent, "message": "Retrieved context.", "data": res})

            elif agent == "db-agent":
                t0 = time.monotonic()
                res = await call_agent("db-agent", {"description": desc, "offline": True})
                dur = int((time.monotonic() - t0) * 1000)
                if "query" not in res:
                    raise ValueError(
                        f"DB agent returned invalid output: missing 'query' key. Got: {list(res.keys())}"
                    )
                step = _step_record(
                    "db-agent", "done",
                    input_summary=desc[:200],
                    output_summary=res.get("query", "")[:200],
                    duration_ms=dur,
                    data=res,
                )
                await _push_step(request_id, step)
                await broadcast({"type": "log", "agent": agent, "message": "Generated query.", "data": res})

                query = res.get("query")
                params = res.get("parameters", [])
                if query:
                    # Cancel check before the executor call too.
                    if await _is_cancelled():
                        await _finalize_run(request_id, "cancelled")
                        return
                    await broadcast({"type": "log", "agent": "DB Executor", "message": f"Executing query: {query}"})
                    t0 = time.monotonic()
                    exec_res = await call_agent("db-executor", {"query": query, "parameters": params})
                    dur = int((time.monotonic() - t0) * 1000)
                    exec_step = _step_record(
                        "db-executor", "done",
                        input_summary=query[:200],
                        output_summary=str(exec_res.get("rows_affected", exec_res))[:200],
                        duration_ms=dur,
                        data=exec_res,
                    )
                    await _push_step(request_id, exec_step)
                    await broadcast({"type": "log", "agent": "DB Executor", "message": "Query executed.", "data": exec_res})

            elif agent == "codegen-agent":
                codegen_res, review_res = await _run_codegen_with_review(
                    desc, context_str, request_id
                )
                final_verdict = review_res.get("final_verdict", "unknown")
                artifact = codegen_res.get("artifact", {})
                last_codegen_artifact = artifact
                # Resolve filename: task target_filename takes precedence.
                filename = _resolve_filename(artifact, desc, task=task)
                code = artifact.get("code")

                # Steps are appended inside _run_codegen_with_review already;
                # we only need to handle the file write here.
                await broadcast({
                    "type": "log", "agent": "Reviewer",
                    "message": f"Review final verdict: {final_verdict}",
                    "data": review_res,
                })

                if code and final_verdict in ("pass", "exhausted"):
                    _write_to_workspace(filename, code, workspace)
                    await broadcast({
                        "type": "log", "agent": "System",
                        "message": f"Wrote {filename} (verdict: {final_verdict})",
                    })
                    await broadcast({"type": "file_update", "filename": filename, "path": os.path.join(workspace, filename)})
                elif final_verdict == "fail":
                    await broadcast({
                        "type": "log", "agent": "System",
                        "message": "File NOT written — review failed with no retry budget remaining.",
                        "status": "warning",
                    })

            elif agent == "reviewer-agent":
                if last_codegen_artifact:
                    req_payload = {"artifact": last_codegen_artifact}
                else:
                    req_payload = {"code": "# No code generated", "language": "python"}
                t0 = time.monotonic()
                res = await call_agent("reviewer-agent", req_payload)
                dur = int((time.monotonic() - t0) * 1000)
                verdict = res.get("verdict", "")
                step = _step_record(
                    "reviewer-agent", "done",
                    input_summary="standalone review",
                    output_summary=f"verdict={verdict}",
                    verdict=verdict,
                    severity_counts=res.get("issues_by_severity", {}),
                    duration_ms=dur,
                    data=res,
                )
                await _push_step(request_id, step)
                await broadcast({
                    "type": "log", "agent": agent,
                    "message": f"Review complete. Verdict: {verdict}", "data": res,
                })

        except Exception as exc:
            logger.error("Agent %s failed: %s", agent, exc)
            step = _step_record(agent, "failed", input_summary=desc[:200], output_summary=str(exc))
            await _push_step(request_id, step)
            await broadcast({
                "type": "log", "agent": agent,
                "message": f"Failed: {exc}", "status": "error",
            })

    await _finalize_run(request_id, "success")


# ---------------------------------------------------------------------------
# CodeGen + Reviewer retry helper
# ---------------------------------------------------------------------------

async def _run_codegen_with_review(
    desc: str,
    context_str: str,
    request_id: str,
    attempt_budget: int = 2,
) -> tuple[dict, dict]:
    """Call Code-Gen then Reviewer with up to attempt_budget total attempts.

    Retry logic:
    - Forwards the full issue list to Code-Gen on retry (full context for LLM).
    - Only error/critical issues trigger a retry; warning/info are logged only.
    - After budget exhausted, returns last result with final_verdict="exhausted".
    - Does NOT write the file on a first-attempt fail.

    Each attempt is pushed as a live step so the caller can observe the
    threaded CodeGen→Reviewer→CodeGen→Reviewer exchange in real time.

    Returns:
        (codegen_result, review_result) — the last pair attempted.
        review_result has a 'final_verdict' key: "pass", "fail", or "exhausted".
    """
    last_codegen_result: dict = {}
    last_review_result: dict = {}
    prior_issues: list = []

    for attempt in range(1, attempt_budget + 1):
        payload: dict = {"description": desc, "context": context_str, "offline": True}
        if attempt > 1 and prior_issues:
            payload["prior_issues"] = prior_issues

        t0 = time.monotonic()
        codegen_result = await call_agent("codegen-agent", payload)
        codegen_dur = int((time.monotonic() - t0) * 1000)

        artifact = codegen_result.get("artifact", {})
        code_snippet = (artifact.get("code") or "")[:120]

        codegen_step = _step_record(
            "codegen-agent", "done",
            attempt_number=attempt,
            input_summary=desc[:200],
            output_summary=f"attempt {attempt}: {code_snippet}",
            duration_ms=codegen_dur,
            data=codegen_result,
        )
        await _push_step(request_id, codegen_step)

        t0 = time.monotonic()
        review_result = await call_agent("reviewer-agent", {"artifact": artifact})
        review_dur = int((time.monotonic() - t0) * 1000)

        verdict = review_result.get("verdict", "unknown")
        severity_counts: dict = review_result.get("issues_by_severity", {})
        prior_issues = review_result.get("issues", [])

        review_step = _step_record(
            "reviewer-agent", "done",
            attempt_number=attempt,
            input_summary=f"review of codegen attempt {attempt}",
            output_summary=f"verdict={verdict} errors={severity_counts.get('error',0)} critical={severity_counts.get('critical',0)}",
            verdict=verdict,
            severity_counts=severity_counts,
            duration_ms=review_dur,
            data=review_result,
        )
        await _push_step(request_id, review_step)

        last_codegen_result = codegen_result
        last_review_result = review_result

        needs_retry = (
            verdict == "fail"
            and (severity_counts.get("error", 0) + severity_counts.get("critical", 0)) > 0
        )

        if verdict == "pass":
            last_review_result["final_verdict"] = "pass"
            return last_codegen_result, last_review_result

        if needs_retry and attempt < attempt_budget:
            logger.info(
                "[%s] Review failed with error/critical issues on attempt %d — retrying.",
                request_id, attempt,
            )
            continue

        if not needs_retry:
            last_review_result["final_verdict"] = "fail"
            return last_codegen_result, last_review_result

    last_review_result["final_verdict"] = "exhausted"
    return last_codegen_result, last_review_result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_workspace(request_id: str) -> str:
    """Return the workspace directory for this run (project dir or default target-app)."""
    state = run_states.get(request_id, {})
    return state.get("workspace_dir") or TARGET_APP_DIR


def _target_path(filename: str, workspace: str | None = None) -> str:
    return os.path.join(workspace or TARGET_APP_DIR, filename)


def _write_to_workspace(filename: str, content: str, workspace: str) -> None:
    """Write content to filename inside the given workspace directory."""
    path = os.path.join(workspace, filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    logger.info("Wrote file: %s", path)


def _resolve_filename(artifact: dict, description: str, task: dict | None = None) -> str:
    """Resolve the output filename.

    Priority:
    1. task['target_filename'] — set by Planner for per-file whole-project subtasks
    2. artifact['filename']    — set by CodeGen agent
    3. Heuristic from description text (legacy fallback)
    """
    # 1. Planner-set target filename (most authoritative)
    if task and task.get("target_filename"):
        return task["target_filename"]
    # 2. CodeGen-set filename
    filename = artifact.get("filename") or artifact.get("name", "generated.py")
    # 3. Legacy description heuristic
    desc_lower = description.lower()
    if "index.html" in desc_lower or ("html" in desc_lower and "index" in desc_lower):
        filename = "index.html"
    elif "style.css" in desc_lower or "styles.css" in desc_lower:
        filename = artifact.get("filename") or "style.css"
    elif "script.js" in desc_lower:
        filename = "script.js"
    elif "readme" in desc_lower:
        filename = "README.md"
    return filename


async def _run_reviewer_gate(artifact: dict) -> dict:
    """Run the Reviewer agent; return a synthetic skip result if unreachable."""
    try:
        return await call_agent("reviewer-agent", {"artifact": artifact})
    except Exception as exc:
        logger.warning("Reviewer gate failed, skipping review: %s", exc)
        return {
            "verdict": "skipped",
            "summary": f"Reviewer unreachable: {exc}",
            "total_issues": 0,
            "issues_by_severity": {},
            "issues": [],
            "categories_checked": [],
        }


async def _handle_system_task(description: str, workspace: str | None = None) -> None:
    """Handle system-level tasks such as project directory cleanup.

    Cleans the given workspace directory (or default target-app/ if not specified).
    """
    target = workspace or TARGET_APP_DIR
    if not os.path.exists(target):
        return
    for filename in os.listdir(target):
        file_path = os.path.join(target, filename)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)
            await broadcast({"type": "file_delete", "filename": filename})
        except Exception as exc:
            logger.error("Failed to delete %s: %s", file_path, exc)
    await broadcast({"type": "log", "agent": "System", "message": "Project directory cleaned up."})


def _write_run_log(run_record: dict) -> None:
    """Write the pipeline run record to a JSON log file."""
    os.makedirs(LOGS_DIR, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"run_{run_record['request_id']}_{timestamp}.json"
    path = os.path.join(LOGS_DIR, filename)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(run_record, fh, indent=2, default=str)
        logger.info("Run log written: %s", path)
    except Exception as exc:
        logger.error("Failed to write run log: %s", exc)


# ---------------------------------------------------------------------------
# File explorer endpoints (restricted to target-app/)
# ---------------------------------------------------------------------------

def _get_dir_structure(path: str) -> dict:
    name = os.path.basename(path)
    if os.path.isdir(path):
        children = []
        for child in sorted(os.listdir(path)):
            if child.startswith("."):
                continue
            children.append(_get_dir_structure(os.path.join(path, child)))
        return {"name": name, "type": "folder", "path": path, "children": children}
    return {"name": name, "type": "file", "path": path}


@app.get("/files")
def get_files(
    project_id: str | None = None,
    current_user: dict = Depends(auth.get_current_user),
) -> dict:
    """Return the directory tree for a workspace.

    If project_id is provided and matches a known run, returns that run's
    workspace tree.  Otherwise returns the default target-app/ tree.
    """
    if project_id and project_id in run_states:
        target = run_states[project_id].get("workspace_dir") or TARGET_APP_DIR
    else:
        target = TARGET_APP_DIR
    if not os.path.exists(target):
        os.makedirs(target, exist_ok=True)
    return _get_dir_structure(target)


@app.get("/file")
def get_file_content(path: str, current_user: dict = Depends(auth.get_current_user)) -> dict:
    """Return the text content of a file.

    Path must be inside target-app/ OR inside any registered project workspace.
    """
    resolved = os.path.realpath(path)
    allowed_roots = [os.path.realpath(TARGET_APP_DIR), os.path.realpath(PROJECTS_DIR)]

    def _is_allowed(p: str) -> bool:
        return any(p.startswith(root) for root in allowed_roots)

    if not _is_allowed(resolved):
        raise HTTPException(
            status_code=403,
            detail="Access denied: path is outside an allowed workspace.",
        )
    try:
        with open(resolved, "r", encoding="utf-8") as fh:
            return {"content": fh.read()}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found.")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/projects")
def list_projects(current_user: dict = Depends(auth.get_current_user)) -> list[dict]:
    """Return a list of all project workspaces created by named runs.

    Each entry contains: request_id, workspace_dir, feature_request, status, file_count.
    """
    result: list[dict] = []
    for rid, state in run_states.items():
        wdir = state.get("workspace_dir")
        if not wdir:
            continue
        file_count = 0
        if os.path.exists(wdir):
            for _, _, files in os.walk(wdir):
                file_count += len(files)
        result.append({
            "request_id": rid,
            "workspace_dir": wdir,
            "feature_request": state.get("feature_request", ""),
            "status": state.get("status", "unknown"),
            "file_count": file_count,
        })
    return result


# ---------------------------------------------------------------------------
# Project auto-run helpers
# ---------------------------------------------------------------------------

def _find_free_port() -> int:
    """Bind to port 0 to get a free ephemeral port from the OS."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _detect_project_type(workspace_dir: str) -> dict:
    """Detect how to run the project in workspace_dir.

    Returns a dict with keys:
      runnable (bool), type (str), reason (str | None),
      command (list[str] | None), cwd (str)
    """
    files = set(os.listdir(workspace_dir)) if os.path.isdir(workspace_dir) else set()

    # Static HTML — serve with Python http.server
    if "index.html" in files and "package.json" not in files:
        return {
            "runnable": True,
            "type": "static",
            "reason": None,
            "command": None,  # built dynamically with port
            "cwd": workspace_dir,
        }

    # Node.js / npm project
    if "package.json" in files:
        pkg_path = os.path.join(workspace_dir, "package.json")
        try:
            with open(pkg_path, encoding="utf-8") as fh:
                pkg = json.load(fh)
            scripts = pkg.get("scripts", {})
            script = "dev" if "dev" in scripts else "start" if "start" in scripts else None
            if script:
                return {
                    "runnable": True,
                    "type": "node",
                    "reason": None,
                    "command": ["npm", "run", script],
                    "cwd": workspace_dir,
                }
        except Exception:
            pass
        return {
            "runnable": False,
            "type": "node",
            "reason": "package.json found but no 'dev' or 'start' script detected.",
            "command": None,
            "cwd": workspace_dir,
        }

    # Python project
    has_requirements = "requirements.txt" in files
    entry_py = next((f for f in ["app.py", "main.py", "server.py"] if f in files), None)
    if has_requirements and entry_py:
        return {
            "runnable": True,
            "type": "python",
            "reason": None,
            "command": [sys.executable, entry_py],
            "cwd": workspace_dir,
        }
    if entry_py:
        return {
            "runnable": True,
            "type": "python",
            "reason": None,
            "command": [sys.executable, entry_py],
            "cwd": workspace_dir,
        }

    return {
        "runnable": False,
        "type": "unknown",
        "reason": (
            f"Could not detect project type. Files found: {sorted(files) or 'none'}. "
            "Expected index.html (static), package.json (node), or app.py/main.py (python)."
        ),
        "command": None,
        "cwd": workspace_dir,
    }


@app.post("/projects/{project_id}/run")
async def run_project(
    project_id: str,
    current_user: dict = Depends(auth.get_current_user),
) -> dict:
    """Detect project type and start the app on a free port.

    Returns:
      { runnable: bool, url: str|null, port: int|null, type: str, reason: str|null }

    Never fakes a running state — if the project can't be detected or launched,
    runnable=False is returned with a plain-text reason.
    """
    state = run_states.get(project_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Run {project_id} not found.")
    workspace_dir = state.get("workspace_dir")
    if not workspace_dir or not os.path.isdir(workspace_dir):
        return {
            "runnable": False,
            "type": "unknown",
            "reason": "No project workspace directory found for this run.",
            "url": None,
            "port": None,
        }

    # Kill any existing process for this project.
    existing = running_processes.get(project_id)
    if existing:
        try:
            existing["process"].terminate()
        except Exception:
            pass
        del running_processes[project_id]

    detection = _detect_project_type(workspace_dir)
    if not detection["runnable"]:
        return {
            "runnable": False,
            "type": detection["type"],
            "reason": detection["reason"],
            "url": None,
            "port": None,
        }

    port = _find_free_port()
    project_type = detection["type"]

    try:
        if project_type == "static":
            # Serve with Python http.server — cross-platform, no npm required.
            cmd = [sys.executable, "-m", "http.server", str(port)]
            process = subprocess.Popen(
                cmd,
                cwd=workspace_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                # Windows: isolate process group so we can terminate cleanly
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
            )
        else:
            # Node or Python project — shell=True required on Windows for npm
            cmd = detection["command"]
            use_shell = sys.platform == "win32" and project_type == "node"
            process = subprocess.Popen(
                cmd if not use_shell else " ".join(cmd),
                cwd=workspace_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=use_shell,
                env={**os.environ, "PORT": str(port)},
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
            )

        # Wait briefly to confirm the process started (doesn't immediately crash).
        await asyncio.sleep(1.5)
        if process.poll() is not None:
            # Process exited already — read stderr for diagnosis.
            _, err = process.communicate(timeout=2)
            return {
                "runnable": False,
                "type": project_type,
                "reason": f"Process exited immediately. Stderr: {err.decode(errors='replace')[:400]}",
                "url": None,
                "port": None,
            }

        url = f"http://localhost:{port}"
        running_processes[project_id] = {
            "pid": process.pid,
            "port": port,
            "url": url,
            "type": project_type,
            "process": process,
        }
        logger.info("Project %s running at %s (pid=%d)", project_id, url, process.pid)
        return {
            "runnable": True,
            "type": project_type,
            "reason": None,
            "url": url,
            "port": port,
        }

    except Exception as exc:
        logger.error("Failed to start project %s: %s", project_id, exc)
        return {
            "runnable": False,
            "type": project_type,
            "reason": f"Failed to launch: {exc}",
            "url": None,
            "port": None,
        }


@app.get("/projects/{project_id}/run-status")
def get_project_run_status(
    project_id: str,
    current_user: dict = Depends(auth.get_current_user),
) -> dict:
    """Return the current run state of a launched project process."""
    info = running_processes.get(project_id)
    if not info:
        return {"status": "not_started", "url": None, "port": None}
    process = info["process"]
    if process.poll() is None:
        return {"status": "running", "url": info["url"], "port": info["port"]}
    return {"status": "stopped", "url": None, "port": None}


@app.post("/projects/{project_id}/stop")
def stop_project(
    project_id: str,
    current_user: dict = Depends(auth.get_current_user),
) -> dict:
    """Kill a running project process."""
    info = running_processes.pop(project_id, None)
    if not info:
        return {"status": "not_running"}
    process = info["process"]
    try:
        if sys.platform == "win32":
            process.send_signal(_signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
        else:
            process.terminate()
        process.wait(timeout=5)
    except Exception:
        process.kill()
    logger.info("Project %s stopped (pid=%d)", project_id, info["pid"])
    return {"status": "stopped", "pid": info["pid"]}


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8020, reload=True)
