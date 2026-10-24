# backend/agent.py
"""Agent loop orchestrator: multi-step planning, tool validation, human-in-the-loop approvals, and SSE streaming."""

import asyncio
import json
import logging
import os
import re
import time
from typing import Any, AsyncGenerator, Dict, List, Optional, Set, Tuple

from context import build_context
from llm import stream_chat
from n8n_client import trigger_workflow
from safety import (
    MAX_STEPS,
    check_rate_limit,
    is_sensitive_read_path,
    is_sensitive_write_path,
    resolve_safe_path,
    validate_command,
)
from store import (
    add_audit_log,
    add_message,
    create_approval,
    get_approval,
    get_messages,
    get_session,
    resolve_approval,
)
from tools import (
    TOOL_DEFINITIONS,
    stop_session_process,
    tool_delete_file,
    tool_edit_file,
    tool_find_files,
    tool_list_dir,
    tool_read_file,
    tool_run_command,
    tool_search_text,
    tool_write_file,
)

logger = logging.getLogger("backend.agent")

# Active session stop events and pending approvals
stop_events: Dict[str, asyncio.Event] = {}
pending_approvals: Dict[str, asyncio.Future] = {}


def request_stop(session_id: str) -> bool:
    """Trigger stop for a session (kills running process and sets stop event)."""
    proc_stopped = stop_session_process(session_id)
    ev = stop_events.get(session_id)
    ev_stopped = False
    if ev:
        ev.set()
        ev_stopped = True
    return proc_stopped or ev_stopped


def resolve_pending_approval(approval_id: str, action: str, auto_approve_all: bool = False, session_id: Optional[str] = None) -> bool:
    """Resolve an in-memory future for approval from user UI."""
    fut = pending_approvals.get(approval_id)
    status = "approved" if action == "approve" else "rejected"
    resolve_approval(approval_id, status)
    if fut and not fut.done():
        fut.set_result({"action": action, "auto_approve_all": auto_approve_all})
        pending_approvals.pop(approval_id, None)
        return True
    return False


def validate_tool_args(tool_name: str, args: Dict[str, Any]) -> Tuple[bool, str]:
    """Validate tool call arguments against schema."""
    schema = next((t["function"] for t in TOOL_DEFINITIONS if t["function"]["name"] == tool_name), None)
    if not schema:
        return False, f"Unknown tool '{tool_name}'."

    required = schema.get("parameters", {}).get("required", [])
    for field in required:
        if field not in args:
            return False, f"Missing required parameter '{field}' for tool '{tool_name}'."
    return True, ""


def extract_plan(text: str) -> Optional[List[str]]:
    """Detect numbered plan in model output."""
    lines = text.splitlines()
    plan_steps = []
    step_re = re.compile(r"^\s*(\d+)[\.\)]\s+(.+)$")
    for line in lines:
        match = step_re.match(line)
        if match:
            plan_steps.append(match.group(2).strip())
    return plan_steps if len(plan_steps) >= 2 else None


async def run_agent_loop(
    session_id: str,
    user_prompt: str,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Main Agent Loop:
    Yields SSE events:
      {"event": "token", "data": {...}}
      {"event": "plan", "data": {...}}
      {"event": "tool_call", "data": {...}}
      {"event": "approval_required", "data": {...}}
      {"event": "tool_result", "data": {...}}
      {"event": "file_changed", "data": {...}}
      {"event": "terminal", "data": {...}}
      {"event": "error", "data": {...}}
      {"event": "done", "data": {...}}
    """
    session = get_session(session_id)
    if not session:
        yield {"event": "error", "data": {"message": f"Session {session_id} not found."}}
        return

    workspace_root = session["workspace_path"]
    model = session["model"]
    auto_approve_writes = session["auto_approve_writes"]

    # Initialize stop event
    stop_event = asyncio.Event()
    stop_events[session_id] = stop_event

    # Persist user message to SQLite
    add_message(session_id, "user", user_prompt)

    history = get_messages(session_id)
    # Exclude the latest user message from history because build_context attaches user_prompt
    raw_history = history[:-1] if len(history) > 1 else []

    recently_read: List[str] = []
    files_modified: Set[str] = set()
    executed_steps = 0
    current_plan: Optional[List[str]] = None

    # Build prompt messages
    messages = await build_context(
        session_id=session_id,
        user_message=user_prompt,
        raw_history=raw_history,
        workspace_root=workspace_root,
        model=model,
        recently_read_files=recently_read,
    )

    try:
        while executed_steps < MAX_STEPS:
            if stop_event.is_set():
                yield {"event": "done", "data": {"status": "stopped", "message": "Turn stopped by operator."}}
                return

            executed_steps += 1
            step_tokens = ""
            tool_calls_to_run = []
            turn_failed = False

            # Stream response from Ollama
            async for chunk in stream_chat(model=model, messages=messages, tools=TOOL_DEFINITIONS):
                if stop_event.is_set():
                    yield {"event": "done", "data": {"status": "stopped", "message": "Turn stopped by operator."}}
                    return

                chunk_type = chunk.get("type")
                if chunk_type == "token":
                    t = chunk.get("content", "")
                    step_tokens += t
                    yield {"event": "token", "data": {"token": t}}

                    # Check for plan generation on the fly
                    if not current_plan and ("\n" in t or len(step_tokens) > 50):
                        detected = extract_plan(step_tokens)
                        if detected:
                            current_plan = detected
                            yield {"event": "plan", "data": {"steps": current_plan}}

                elif chunk_type == "tool_call":
                    tool_calls_to_run.append(chunk["tool_call"])

                elif chunk_type == "error":
                    yield {"event": "error", "data": {"message": chunk.get("message", "LLM Error")}}
                    turn_failed = True
                    break

            if turn_failed:
                break

            # If model produced text, append assistant message to conversation context
            if step_tokens:
                messages.append({"role": "assistant", "content": step_tokens})
                # Check plan after full tokens if not detected yet
                if not current_plan:
                    detected = extract_plan(step_tokens)
                    if detected:
                        current_plan = detected
                        yield {"event": "plan", "data": {"steps": current_plan}}

            # If this task needs multi-step work, emit the plan event BEFORE the first tool call
            if not current_plan and len(tool_calls_to_run) >= 1:
                detected = extract_plan(step_tokens)
                if detected:
                    current_plan = detected
                else:
                    current_plan = [
                        f"Step 1: Execute tool '{tc.get('name')}' to implement required changes"
                        for tc in tool_calls_to_run
                    ]
                    current_plan.append("Step 2: Verify execution results and run tests/checks")
                    current_plan.append("Step 3: Provide summary of changes")
            # If no tools were called, the turn is complete.
            if not tool_calls_to_run:
                if step_tokens:
                    add_message(session_id, "assistant", step_tokens, metadata={"steps": executed_steps})
                yield {"event": "done", "data": {"status": "completed", "summary": step_tokens}}
                break

            # Execute tool calls
            tool_retries: Dict[str, int] = {}
            for tool_idx, tc in enumerate(tool_calls_to_run):
                if stop_event.is_set():
                    yield {"event": "done", "data": {"status": "stopped", "message": "Turn stopped by operator."}}
                    return

                tool_name = tc.get("name", "")
                args = tc.get("arguments", {})
                call_id = tc.get("id", f"call_{int(time.time()*1000)}")

                yield {
                    "event": "tool_call",
                    "data": {"name": tool_name, "arguments": args, "id": call_id},
                }

                # Step 4: Validate tool arguments with maximum 2 retries
                valid, val_err = validate_tool_args(tool_name, args)
                if not valid:
                    attempt = tool_retries.get(tool_name, 0) + 1
                    tool_retries[tool_name] = attempt
                    if attempt <= 2:
                        error_msg = f"Tool argument error: {val_err}. Retry {attempt}/2: Please fix parameters to match schema."
                    else:
                        error_msg = f"Tool {tool_name} aborted: exceeded maximum 2 retries on invalid arguments ({val_err})."

                    yield {
                        "event": "tool_result",
                        "data": {"name": tool_name, "id": call_id, "success": False, "output": error_msg},
                    }
                    messages.append({
                        "role": "tool",
                        "name": tool_name,
                        "content": json.dumps({"error": error_msg, "retry_attempt": attempt}),
                    })
                    continue

                # Rate limit check
                rate_ok, rate_err = check_rate_limit()
                if not rate_ok:
                    yield {"event": "error", "data": {"message": rate_err}}
                    yield {"event": "done", "data": {"status": "rate_limited", "message": rate_err}}
                    return

                # Step 5: Safety checks and Human-in-the-Loop approvals
                needs_approval = False
                approval_reason = ""

                if tool_name in ("write_file", "edit_file", "delete_file"):
                    target_p = args.get("path", "")
                    if is_sensitive_write_path(target_p):
                        needs_approval = True
                        approval_reason = f"File '{target_p}' is on the sensitive deny list."
                    elif not auto_approve_writes:
                        needs_approval = True
                        approval_reason = f"File modification requires operator approval: {tool_name} '{target_p}'."
                elif tool_name == "read_file":
                    target_p = args.get("path", "")
                    if is_sensitive_read_path(target_p):
                        needs_approval = True
                        approval_reason = f"Reading sensitive configuration file '{target_p}' requires explicit approval."
                elif tool_name == "run_command":
                    needs_approval = True
                    approval_reason = f"Executing command '{args.get('command')}' requires operator confirmation."
                elif tool_name == "trigger_workflow":
                    needs_approval = True
                    approval_reason = f"Triggering external automation workflow '{args.get('name')}'."

                approval_id = None
                if needs_approval:
                    appr_record = create_approval(
                        session_id=session_id,
                        tool_name=tool_name,
                        arguments=args,
                        reason=approval_reason,
                    )
                    approval_id = appr_record["id"]
                    add_audit_log(session_id, tool_name, args, status="pending_approval", approval_id=approval_id)

                    yield {
                        "event": "approval_required",
                        "data": {
                            "approval_id": approval_id,
                            "tool": tool_name,
                            "arguments": args,
                            "reason": approval_reason,
                        },
                    }

                    # Wait for user decision with 5-minute timeout
                    fut = asyncio.get_event_loop().create_future()
                    pending_approvals[approval_id] = fut
                    try:
                        decision = await asyncio.wait_for(fut, timeout=300.0)
                    except asyncio.TimeoutError:
                        resolve_approval(approval_id, "timeout")
                        decision = {"action": "reject", "reason": "timeout"}
                    finally:
                        pending_approvals.pop(approval_id, None)

                    if decision.get("action") != "approve":
                        status_str = "timeout" if decision.get("reason") == "timeout" else "rejected"
                        reject_msg = f"Operation was {status_str} by operator or timed out after 5 minutes."
                        add_audit_log(session_id, tool_name, args, status=status_str, result=reject_msg, approval_id=approval_id)
                        yield {
                            "event": "tool_result",
                            "data": {"name": tool_name, "id": call_id, "success": False, "output": reject_msg},
                        }
                        messages.append({"role": "tool", "name": tool_name, "content": reject_msg})
                        continue
                    else:
                        add_audit_log(session_id, tool_name, args, status="approved", result="Operator approved execution.", approval_id=approval_id)
                        if decision.get("auto_approve_all"):
                            auto_approve_writes = True

                # Step 6: Execute tool
                success = False
                output = ""
                extra: Dict[str, Any] = {}

                if tool_name == "list_dir":
                    success, output, extra = tool_list_dir(workspace_root, args.get("path", ""))

                elif tool_name == "read_file":
                    p = args.get("path", "")
                    success, output, extra = tool_read_file(workspace_root, p, args.get("start_line"), args.get("end_line"))
                    if success:
                        recently_read.insert(0, p)

                elif tool_name == "search_text":
                    success, output, extra = tool_search_text(workspace_root, args.get("query", ""), args.get("glob"))

                elif tool_name == "find_files":
                    success, output, extra = tool_find_files(workspace_root, args.get("glob", ""))

                elif tool_name == "write_file":
                    p = args.get("path", "")
                    success, output, extra = tool_write_file(workspace_root, p, args.get("content", ""))
                    if success:
                        files_modified.add(p)
                        yield {
                            "event": "file_changed",
                            "data": {"path": p, "before": extra.get("before", ""), "after": extra.get("after", "")},
                        }

                elif tool_name == "edit_file":
                    p = args.get("path", "")
                    success, output, extra = tool_edit_file(workspace_root, p, args.get("old_text", ""), args.get("new_text", ""))
                    if success:
                        files_modified.add(p)
                        yield {
                            "event": "file_changed",
                            "data": {"path": p, "before": extra.get("before", ""), "after": extra.get("after", "")},
                        }

                elif tool_name == "delete_file":
                    p = args.get("path", "")
                    success, output, extra = tool_delete_file(workspace_root, p)
                    if success:
                        files_modified.add(p)
                        yield {
                            "event": "file_changed",
                            "data": {"path": p, "before": extra.get("before", ""), "after": ""},
                        }

                elif tool_name == "run_command":
                    def on_terminal_chunk(chunk_str: str):
                        # Queue terminal event asynchronously
                        try:
                            loop = asyncio.get_event_loop()
                            # We can yield in main generator or push to a queue; for now, terminal event is emitted below
                        except Exception:
                            pass

                    cmd_str = args.get("command", "")
                    success, output, extra = await tool_run_command(
                        workspace_root=workspace_root,
                        command=cmd_str,
                        cwd=args.get("cwd"),
                        timeout_seconds=args.get("timeout_seconds"),
                        session_id=session_id,
                    )
                    # Emit live terminal event
                    yield {
                        "event": "terminal",
                        "data": {"command": cmd_str, "output": extra.get("output", output), "returncode": extra.get("returncode", 0)},
                    }

                elif tool_name == "trigger_workflow":
                    wf_res = await trigger_workflow(args.get("name", ""), args.get("payload", {}))
                    success = wf_res.get("success", False)
                    output = json.dumps(wf_res)

                # Log audit in SQLite with approval_id
                add_audit_log(session_id, tool_name, args, status="success" if success else "failed", result=output, approval_id=approval_id)

                # Emit tool_result event
                yield {
                    "event": "tool_result",
                    "data": {"name": tool_name, "id": call_id, "success": success, "output": output},
                }

                # Update plan status as steps finish
                if current_plan:
                    yield {
                        "event": "plan",
                        "data": {
                            "steps": current_plan,
                            "completed_step": tool_idx + 1,
                            "current_step": tool_idx + 2,
                            "status": "in_progress" if (tool_idx + 1 < len(tool_calls_to_run)) else "verifying"
                        }
                    }

                # Append tool result to LLM messages
                messages.append({
                    "role": "tool",
                    "name": tool_name,
                    "content": output,
                })

        # Hit step limit
        limit_summary = (
            f"Step limit ({MAX_STEPS}) reached. "
            f"Modified files: {', '.join(files_modified) if files_modified else 'None'}. "
            "Please review the changes or prompt me to continue the remaining tasks."
        )
        add_message(session_id, "assistant", limit_summary, metadata={"steps": executed_steps, "limit_reached": True})
        yield {"event": "token", "data": {"token": "\n\n" + limit_summary}}
        yield {"event": "done", "data": {"status": "limit_reached", "summary": limit_summary}}

    finally:
        stop_events.pop(session_id, None)
