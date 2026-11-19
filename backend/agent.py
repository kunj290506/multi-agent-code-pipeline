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
from validator import validate_workspace_file

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


def _unescape_if_json_string(code: str) -> str:
    """If extracted code has literal \\n and \\\" from an unparsed JSON string, restore real newlines and quotes."""
    if "\\n" in code and code.count("\n") <= 2 and ('\\"' in code or "<html" in code.lower() or "<!doctype" in code.lower()):
        return (
            code.replace("\\r\\n", "\n")
            .replace("\\n", "\n")
            .replace("\\t", "\t")
            .replace('\\"', '"')
            .replace("\\'", "'")
            .replace("\\\\", "\\")
        )
    return code


def _extract_fallback_file_write(user_prompt: str, assistant_text: str) -> Optional[Dict[str, Any]]:
    """
    If a smaller local model prints a complete code/HTML file directly in chat instead of calling
    write_file, extract it into a synthetic write_file tool call so the workspace is actually built.
    """
    if not assistant_text or len(assistant_text) < 40:
        return None

    # 1. Check for fenced HTML block or full HTML document
    html_block = re.search(r"```html\s*([\s\S]*?)```", assistant_text, re.IGNORECASE)
    if html_block and ("<html" in html_block.group(1).lower() or "<!doctype html" in html_block.group(1).lower()):
        code = _unescape_if_json_string(html_block.group(1).strip())
        target_match = re.search(r"\b([A-Za-z0-9_./-]+\.html?)\b", user_prompt, re.IGNORECASE)
        target_path = target_match.group(1) if target_match else "index.html"
        return {
            "name": "write_file",
            "arguments": {"path": target_path, "content": code},
            "id": f"autosave_{int(time.time() * 1000)}",
        }

    raw_html = re.search(r"(<!DOCTYPE\s+html[\s\S]*?</html>)", assistant_text, re.IGNORECASE)
    if raw_html:
        code = _unescape_if_json_string(raw_html.group(1).strip())
        target_match = re.search(r"\b([A-Za-z0-9_./-]+\.html?)\b", user_prompt, re.IGNORECASE)
        target_path = target_match.group(1) if target_match else "index.html"
        return {
            "name": "write_file",
            "arguments": {"path": target_path, "content": code},
            "id": f"autosave_{int(time.time() * 1000)}",
        }

    # 2. Check if user explicitly asked to create a specific .py / .js / .css file and model emitted a fenced block
    create_intent = bool(re.search(r"\b(create|write|build|make|generate)\b", user_prompt, re.IGNORECASE))
    if create_intent:
        file_match = re.search(r"\b([A-Za-z0-9_/-]+\.(?:py|js|mjs|ts|css))\b", user_prompt)
        if file_match:
            target_path = file_match.group(1)
            ext = os.path.splitext(target_path)[1].lower()
            lang_map = {".py": "python|py", ".js": "javascript|js", ".mjs": "javascript|js", ".ts": "typescript|ts", ".css": "css"}
            lang_pat = lang_map.get(ext, "")
            code_match = re.search(rf"```(?:{lang_pat})?\s*\n([\s\S]*?)```", assistant_text, re.IGNORECASE)
            if code_match and code_match.group(1).strip():
                return {
                    "name": "write_file",
                    "arguments": {"path": target_path, "content": code_match.group(1).strip() + "\n"},
                    "id": f"autosave_{int(time.time() * 1000)}",
                }
    return None


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
    repair_attempts = 0
    consecutive_edit_failures = 0
    last_tool_signature: Optional[str] = None
    repeat_tool_count = 0
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
                yield {"event": "done", "data": {"status": "stopped", "message": "Turn stopped by operator.", "files_modified": sorted(files_modified)}}
                return

            executed_steps += 1
            step_tokens = ""
            tool_calls_to_run = []
            turn_failed = False

            # Stream response from Ollama
            async for chunk in stream_chat(model=model, messages=messages, tools=TOOL_DEFINITIONS):
                if stop_event.is_set():
                    yield {"event": "done", "data": {"status": "stopped", "message": "Turn stopped by operator.", "files_modified": sorted(files_modified)}}
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
                return

            # Fallback: if model printed full code/HTML in chat without calling write_file, extract it automatically
            if not tool_calls_to_run and not files_modified and step_tokens:
                fallback_tc = _extract_fallback_file_write(user_prompt, step_tokens)
                if fallback_tc:
                    logger.info(f"Auto-extracted fallback write_file for '{fallback_tc['arguments'].get('path')}' from assistant response.")
                    tool_calls_to_run.append(fallback_tc)

            # Append assistant message properly (including tool_calls so Ollama multi-step context stays valid!)
            if step_tokens or tool_calls_to_run:
                assistant_msg: Dict[str, Any] = {"role": "assistant", "content": step_tokens}
                if tool_calls_to_run:
                    assistant_msg["tool_calls"] = [
                        {"function": {"name": tc.get("name", ""), "arguments": tc.get("arguments", {})}}
                        for tc in tool_calls_to_run
                    ]
                messages.append(assistant_msg)
                if step_tokens and not current_plan:
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
                        f"Execute {tc.get('name')} ({tc.get('arguments', {}).get('path') or tc.get('arguments', {}).get('command') or ''})".strip()
                        for tc in tool_calls_to_run
                    ]
                    current_plan.append("Verify generated code for syntax and interactivity bugs")
                    current_plan.append("Finalize and summarize changes")
                yield {"event": "plan", "data": {"steps": current_plan}}

            # If no tools were called, run final automated verification before completing!
            if not tool_calls_to_run:
                if files_modified and repair_attempts < 2:
                    all_final_errors: List[str] = []
                    for mod_p in sorted(files_modified):
                        val_res = validate_workspace_file(workspace_root, mod_p, check_missing_assets=True, strict_assets=True)
                        if not val_res["valid"]:
                            all_final_errors.extend(val_res["errors"])

                    if all_final_errors:
                        repair_attempts += 1
                        err_bullets = "\n".join(f"- {e}" for e in all_final_errors)
                        logger.warning(f"Final verification failed (attempt {repair_attempts}/2): {all_final_errors}")
                        yield {
                            "event": "tool_result",
                            "data": {
                                "name": "verify_project",
                                "id": f"verify_{int(time.time() * 1000)}",
                                "success": False,
                                "output": f"Automated verification detected issues (auto-fixing {repair_attempts}/2):\n{err_bullets}",
                            },
                        }
                        messages.append({
                            "role": "user",
                            "content": (
                                "Automated verification found these bugs in your generated files:\n"
                                f"{err_bullets}\n\n"
                                "Please fix ALL of these bugs right now using `edit_file` or `write_file` "
                                "so the demo runs cleanly and is 100% interactive."
                            ),
                        })
                        continue

                if step_tokens:
                    add_message(session_id, "assistant", step_tokens, metadata={"steps": executed_steps})
                yield {
                    "event": "done",
                    "data": {
                        "status": "completed",
                        "summary": step_tokens,
                        "files_modified": sorted(files_modified),
                    },
                }
                return

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

                # Duplicate tool call loop breaker (prevents small models repeating the same broken edit)
                sig = f"{tool_name}:{json.dumps(args, sort_keys=True)}"
                if sig == last_tool_signature:
                    repeat_tool_count += 1
                    if repeat_tool_count >= 2:
                        loop_msg = (
                            f"Stopped repeating identical {tool_name} call. "
                            "Instead of repeating edit_file, rewrite the entire fixed file cleanly using write_file, "
                            "or summarize the current state if the file is ready."
                        )
                        yield {
                            "event": "tool_result",
                            "data": {"name": tool_name, "id": call_id, "success": False, "output": loop_msg},
                        }
                        messages.append({"role": "tool", "name": tool_name, "content": loop_msg})
                        continue
                else:
                    last_tool_signature = sig
                    repeat_tool_count = 0

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
                    raw_content = _unescape_if_json_string(args.get("content", ""))
                    success, output, extra = tool_write_file(workspace_root, p, raw_content)
                    if success:
                        files_modified.add(p)
                        consecutive_edit_failures = 0
                        yield {
                            "event": "file_changed",
                            "data": {"path": p, "before": extra.get("before", ""), "after": extra.get("after", "")},
                        }
                        val_res = validate_workspace_file(workspace_root, p, check_missing_assets=True, strict_assets=False)
                        if not val_res["valid"]:
                            err_text = "\n".join(f"- {e}" for e in val_res["errors"])
                            output += (
                                f"\n\n[AUTOMATED VALIDATION FAILED — FIX IMMEDIATELY]:\n{err_text}\n"
                                "Fix these issues cleanly using write_file with the complete corrected file before finishing."
                            )
                        elif val_res["warnings"]:
                            warn_text = "\n".join(f"- {w}" for w in val_res["warnings"])
                            output += f"\n\n[VALIDATION NOTES]:\n{warn_text}"
                        else:
                            output += "\n[VALIDATION PASSED: syntax and DOM interactivity checks passed.]"

                elif tool_name == "edit_file":
                    p = args.get("path", "")
                    success, output, extra = tool_edit_file(workspace_root, p, args.get("old_text", ""), args.get("new_text", ""))
                    if success:
                        files_modified.add(p)
                        yield {
                            "event": "file_changed",
                            "data": {"path": p, "before": extra.get("before", ""), "after": extra.get("after", "")},
                        }
                        val_res = validate_workspace_file(workspace_root, p, check_missing_assets=True, strict_assets=False)
                        if not val_res["valid"]:
                            consecutive_edit_failures += 1
                            err_text = "\n".join(f"- {e}" for e in val_res["errors"])
                            hint = (
                                "Multiple partial edits failed validation — rewrite the complete clean file in one `write_file` call."
                                if consecutive_edit_failures >= 2
                                else "Fix these issues right now using edit_file or write_file before finishing."
                            )
                            output += f"\n\n[AUTOMATED VALIDATION FAILED — FIX IMMEDIATELY]:\n{err_text}\n{hint}"
                        elif val_res["warnings"]:
                            consecutive_edit_failures = 0
                            warn_text = "\n".join(f"- {w}" for w in val_res["warnings"])
                            output += f"\n\n[VALIDATION NOTES]:\n{warn_text}"
                        else:
                            consecutive_edit_failures = 0
                            output += "\n[VALIDATION PASSED: syntax and DOM interactivity checks passed.]"

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
        yield {"event": "done", "data": {"status": "limit_reached", "summary": limit_summary, "files_modified": sorted(files_modified)}}

    finally:
        stop_events.pop(session_id, None)
