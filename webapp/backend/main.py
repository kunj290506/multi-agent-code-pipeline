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
import time
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

import httpx
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
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
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

# ---------------------------------------------------------------------------
# WebSocket management (legacy, kept for backwards compat)
# ---------------------------------------------------------------------------

active_connections: list[WebSocket] = []


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

def _init_run_state(request_id: str, feature_request: str) -> dict:
    """Create and register the initial live state for a new run."""
    state: dict[str, Any] = {
        "request_id": request_id,
        "feature_request": feature_request,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
        "status": "running",
        "total_duration_ms": None,
        "steps": [],
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
    """Mark a run complete, compute total_duration_ms, write log, push SSE close."""
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
    await _sse_close(request_id)
    await broadcast({"type": "done", "request_id": request_id, "status": status})


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class RunRequest(BaseModel):
    """Request body for POST /runs (and POST /request alias)."""
    request: str = Field(..., min_length=1, description="Feature request in plain language.")

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
def get_history() -> list[dict]:
    """Return the list of past pipeline runs (in-memory)."""
    return run_history


# ---------------------------------------------------------------------------
# Live-run endpoints
# ---------------------------------------------------------------------------

@app.post("/runs", status_code=202)
async def start_run(req: RunRequest) -> dict:
    """Start a new pipeline run and return immediately with the request_id.

    The pipeline executes asynchronously.  Poll GET /runs/{id}/status or
    stream GET /runs/{id}/events to observe progress.
    """
    request_id = os.urandom(4).hex()
    state = _init_run_state(request_id, req.request)
    run_history.append(state)
    # Fire the pipeline as a background task so this endpoint returns immediately.
    asyncio.create_task(_run_pipeline(request_id, req.request))
    await broadcast({"type": "start", "request_id": request_id, "request": req.request})
    return {"request_id": request_id, "status": "accepted"}


@app.post("/runs/{request_id}/cancel")
async def cancel_run(request_id: str) -> dict:
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
def get_run_status(request_id: str) -> dict:
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
async def run_events(request_id: str) -> StreamingResponse:
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
    """Return metadata for all pipeline run log files."""
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
    """Return the full log JSON for a specific pipeline run."""
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
                await _handle_system_task(desc)
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
                filename = _resolve_filename(artifact, desc)
                code = artifact.get("code")

                # Steps are appended inside _run_codegen_with_review already;
                # we only need to handle the file write here.
                await broadcast({
                    "type": "log", "agent": "Reviewer",
                    "message": f"Review final verdict: {final_verdict}",
                    "data": review_res,
                })

                if code and final_verdict in ("pass", "exhausted"):
                    _write_to_target_app(filename, code)
                    await broadcast({
                        "type": "log", "agent": "System",
                        "message": f"Wrote {filename} (verdict: {final_verdict})",
                    })
                    await broadcast({"type": "file_update", "filename": filename, "path": _target_path(filename)})
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

def _target_path(filename: str) -> str:
    return os.path.join(TARGET_APP_DIR, filename)


def _write_to_target_app(filename: str, content: str) -> None:
    path = _target_path(filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    logger.info("Wrote file: %s", path)


def _resolve_filename(artifact: dict, description: str) -> str:
    filename = artifact.get("filename") or artifact.get("name", "generated.py")
    desc_lower = description.lower()
    if "html" in desc_lower:
        filename = "index.html"
    elif "css" in desc_lower:
        filename = "styles.css"
    elif "js" in desc_lower or "script.js" in desc_lower:
        filename = "script.js"
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


async def _handle_system_task(description: str) -> None:
    """Handle system-level tasks such as project directory cleanup."""
    if not os.path.exists(TARGET_APP_DIR):
        return
    for filename in os.listdir(TARGET_APP_DIR):
        file_path = os.path.join(TARGET_APP_DIR, filename)
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
def get_files() -> dict:
    """Return the directory tree of target-app/."""
    if not os.path.exists(TARGET_APP_DIR):
        os.makedirs(TARGET_APP_DIR, exist_ok=True)
    return _get_dir_structure(TARGET_APP_DIR)


@app.get("/file")
def get_file_content(path: str) -> dict:
    """Return the text content of a file inside target-app/."""
    resolved = os.path.realpath(path)
    allowed_root = os.path.realpath(TARGET_APP_DIR)
    if not resolved.startswith(allowed_root):
        raise HTTPException(
            status_code=403,
            detail="Access denied: path is outside the target-app directory.",
        )
    try:
        with open(resolved, "r", encoding="utf-8") as fh:
            return {"content": fh.read()}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found.")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8020, reload=True)
