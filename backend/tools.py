# backend/tools.py
"""Tool definitions and implementations for the coding agent."""

import asyncio
import fnmatch
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from safety import (
    MAX_OUTPUT_BYTES,
    MAX_OUTPUT_LINES,
    MAX_READ_BYTES,
    MAX_WRITE_BYTES,
    is_sensitive_read_path,
    is_sensitive_write_path,
    resolve_safe_path,
    validate_command,
    wrap_untrusted_data,
)
from store import save_file_backup

# Active processes tracked for live cancellation
active_processes: Dict[str, asyncio.subprocess.Process] = {}


# ---------------------------------------------------------------------------
# Tool Schemas for Ollama /api/chat
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List files and subdirectories in a directory inside the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to directory inside workspace (empty string for root)."}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read file contents inside workspace with optional line range.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to file inside workspace."},
                    "start_line": {"type": "integer", "description": "Optional 1-indexed starting line."},
                    "end_line": {"type": "integer", "description": "Optional 1-indexed ending line."}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_text",
            "description": "Search for a text string or regex across files in workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Text to search for."},
                    "glob": {"type": "string", "description": "Optional glob pattern like '*.py' or '*.ts'."}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "find_files",
            "description": "Find files matching a glob pattern inside workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "glob": {"type": "string", "description": "Glob pattern (e.g. '*.py', '**/*.tsx')."}
                },
                "required": ["glob"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create a new file or completely overwrite an existing file inside workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to file inside workspace."},
                    "content": {"type": "string", "description": "Full text content to write."}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Make an exact string replacement in a file. Fails if old_text is not uniquely found.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to file inside workspace."},
                    "old_text": {"type": "string", "description": "Exact text snippet to replace."},
                    "new_text": {"type": "string", "description": "Replacement text."}
                },
                "required": ["path", "old_text", "new_text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "Delete a file inside the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to file inside workspace."}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run an allowed CLI command (python, pytest, node, npm, git read-only) inside workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Command string to execute (e.g. 'pytest -v' or 'python app.py')."},
                    "cwd": {"type": "string", "description": "Optional working directory relative to workspace root."},
                    "timeout_seconds": {"type": "integer", "description": "Max execution time in seconds (max 60)."}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "trigger_workflow",
            "description": "Trigger an automated n8n workflow (allowed: 'run-tests', 'summarize-changes', 'notify').",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Workflow name ('run-tests', 'summarize-changes', 'notify')."},
                    "payload": {"type": "object", "description": "JSON payload parameters."}
                },
                "required": ["name", "payload"]
            }
        }
    }
]


# ---------------------------------------------------------------------------
# Tool Implementations
# ---------------------------------------------------------------------------

def tool_list_dir(workspace_root: str, path: str = "") -> Tuple[bool, str, Dict[str, Any]]:
    is_safe, full_path, err = resolve_safe_path(workspace_root, path)
    if not is_safe:
        return False, f"Error: {err}", {}

    if not os.path.exists(full_path):
        return False, f"Directory '{path}' does not exist.", {}
    if not os.path.isdir(full_path):
        return False, f"Path '{path}' is a file, not a directory.", {}

    ignored = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
    entries = []
    try:
        for entry in os.scandir(full_path):
            if entry.name in ignored:
                continue
            is_dir = entry.is_dir()
            size = entry.stat().st_size if not is_dir else 0
            entries.append({
                "name": entry.name,
                "type": "directory" if is_dir else "file",
                "size": size,
            })
    except Exception as exc:
        return False, f"Error listing directory: {exc}", {}

    entries.sort(key=lambda x: (0 if x["type"] == "directory" else 1, x["name"].lower()))
    lines = [f"{e['type'].upper()[:3]}  {e['name']}" + (f" ({e['size']} B)" if e['type'] == 'file' else "") for e in entries]
    output = "\n".join(lines) if lines else "(empty directory)"
    return True, output, {"entries": entries, "count": len(entries)}


def tool_read_file(
    workspace_root: str,
    path: str,
    start_line: Optional[int] = None,
    end_line: Optional[int] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    is_safe, full_path, err = resolve_safe_path(workspace_root, path)
    if not is_safe:
        return False, f"Error: {err}", {}

    if not os.path.exists(full_path):
        return False, f"File '{path}' does not exist.", {}
    if not os.path.isfile(full_path):
        return False, f"Path '{path}' is a directory, not a file.", {}

    file_size = os.path.getsize(full_path)
    if file_size > MAX_READ_BYTES:
        return False, f"File '{path}' size ({file_size} bytes) exceeds maximum read limit ({MAX_READ_BYTES} bytes).", {}

    try:
        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception as exc:
        return False, f"Error reading file '{path}': {exc}", {}

    total_lines = len(lines)
    s = max(1, start_line) if start_line else 1
    e = min(total_lines, end_line) if end_line else total_lines

    if s > total_lines:
        return False, f"start_line ({s}) exceeds total lines ({total_lines}).", {}

    selected_lines = lines[s - 1:e]
    numbered = [f"{idx:4d} | {line}" for idx, line in enumerate(selected_lines, start=s)]
    raw_content = "".join(selected_lines)
    wrapped = wrap_untrusted_data("".join(numbered), data_type="file_content", source=path)

    notice = ""
    if s > 1 or e < total_lines:
        notice = f"\n(Showing lines {s} to {e} of {total_lines})"

    return True, wrapped + notice, {"path": path, "total_lines": total_lines, "raw": raw_content}


def tool_search_text(workspace_root: str, query: str, glob_pattern: Optional[str] = None) -> Tuple[bool, str, Dict[str, Any]]:
    if not query:
        return False, "Search query cannot be empty.", {}

    ws_real = os.path.realpath(workspace_root)
    ignored = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
    matches = []
    max_matches = 50

    for root, dirs, files in os.walk(ws_real):
        dirs[:] = [d for d in dirs if d not in ignored]
        for f in files:
            if glob_pattern and not fnmatch.fnmatch(f, glob_pattern):
                continue
            full_path = os.path.join(root, f)
            rel_path = os.path.relpath(full_path, ws_real)
            if os.path.getsize(full_path) > MAX_READ_BYTES:
                continue
            try:
                with open(full_path, "r", encoding="utf-8", errors="ignore") as fh:
                    for line_no, line in enumerate(fh, start=1):
                        if query.lower() in line.lower():
                            matches.append(f"{rel_path}:{line_no}: {line.strip()[:150]}")
                            if len(matches) >= max_matches:
                                break
            except Exception:
                continue
        if len(matches) >= max_matches:
            break

    if not matches:
        return True, f"No matches found for '{query}'.", {"count": 0}

    truncation = f"\n(Truncated to first {max_matches} matches)" if len(matches) >= max_matches else ""
    return True, "\n".join(matches) + truncation, {"count": len(matches)}


def tool_find_files(workspace_root: str, glob_pattern: str) -> Tuple[bool, str, Dict[str, Any]]:
    if not glob_pattern:
        return False, "Glob pattern cannot be empty.", {}

    ws_real = os.path.realpath(workspace_root)
    ignored = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
    found = []

    for root, dirs, files in os.walk(ws_real):
        dirs[:] = [d for d in dirs if d not in ignored]
        for f in files:
            rel_path = os.path.relpath(os.path.join(root, f), ws_real).replace("\\", "/")
            if fnmatch.fnmatch(rel_path, glob_pattern) or fnmatch.fnmatch(f, glob_pattern):
                found.append(rel_path)

    if not found:
        return True, f"No files matched pattern '{glob_pattern}'.", {"files": []}

    found.sort()
    return True, "\n".join(found), {"files": found, "count": len(found)}


def tool_write_file(workspace_root: str, path: str, content: str) -> Tuple[bool, str, Dict[str, Any]]:
    is_safe, full_path, err = resolve_safe_path(workspace_root, path)
    if not is_safe:
        return False, f"Error: {err}", {}

    if is_sensitive_write_path(path):
        return False, f"Write blocked: file '{path}' is on the sensitive deny list.", {}

    if len(content.encode("utf-8")) > MAX_WRITE_BYTES:
        return False, f"Content size exceeds maximum write limit ({MAX_WRITE_BYTES} bytes).", {}

    orig_content = ""
    if os.path.exists(full_path):
        try:
            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                orig_content = f.read()
        except Exception:
            pass

    try:
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        # Record backup for undo
        save_file_backup(path, orig_content, content)
    except Exception as exc:
        return False, f"Failed to write file '{path}': {exc}", {}

    return True, f"Successfully wrote {len(content)} characters to '{path}'.", {
        "path": path,
        "before": orig_content,
        "after": content,
    }


def tool_edit_file(workspace_root: str, path: str, old_text: str, new_text: str) -> Tuple[bool, str, Dict[str, Any]]:
    is_safe, full_path, err = resolve_safe_path(workspace_root, path)
    if not is_safe:
        return False, f"Error: {err}", {}

    if is_sensitive_write_path(path):
        return False, f"Edit blocked: file '{path}' is on the sensitive deny list.", {}

    if not os.path.exists(full_path):
        return False, f"File '{path}' does not exist.", {}

    try:
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as exc:
        return False, f"Error reading file '{path}': {exc}", {}

    occurrences = content.count(old_text)
    if occurrences == 0:
        return False, f"Error: old_text was not found in '{path}'. Make sure to match exact whitespace and characters.", {}
    if occurrences > 1:
        return False, f"Error: old_text occurs {occurrences} times in '{path}'. Replacement must be unique. Provide more surrounding context.", {}

    new_content = content.replace(old_text, new_text, 1)

    try:
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        save_file_backup(path, content, new_content)
    except Exception as exc:
        return False, f"Failed to save edit to '{path}': {exc}", {}

    return True, f"Successfully edited '{path}'.", {
        "path": path,
        "before": content,
        "after": new_content,
    }


def tool_delete_file(workspace_root: str, path: str) -> Tuple[bool, str, Dict[str, Any]]:
    is_safe, full_path, err = resolve_safe_path(workspace_root, path)
    if not is_safe:
        return False, f"Error: {err}", {}

    if is_sensitive_write_path(path):
        return False, f"Delete blocked: file '{path}' is on the sensitive deny list.", {}

    if not os.path.exists(full_path):
        return False, f"File '{path}' does not exist.", {}
    if os.path.isdir(full_path):
        return False, f"Delete blocked: '{path}' is a directory. Only file deletion is permitted.", {}

    orig_content = ""
    try:
        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            orig_content = f.read()
    except Exception:
        pass

    try:
        os.remove(full_path)
        save_file_backup(path, orig_content, "")
    except Exception as exc:
        return False, f"Failed to delete '{path}': {exc}", {}

    return True, f"Successfully deleted '{path}'.", {"path": path, "before": orig_content, "after": ""}


async def tool_run_command(
    workspace_root: str,
    command: str,
    cwd: Optional[str] = None,
    timeout_seconds: Optional[int] = None,
    on_output: Optional[Callable[[str], None]] = None,
    session_id: Optional[str] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    is_valid, err, args = validate_command(command, workspace_root, cwd)
    if not is_valid:
        return False, f"Command validation failed: {err}", {}

    exec_cwd = os.path.realpath(os.path.join(workspace_root, cwd)) if cwd else os.path.realpath(workspace_root)
    timeout = min(timeout_seconds or 30, 60)

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=exec_cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        if session_id:
            active_processes[session_id] = proc

        stdout_chunks: List[str] = []
        stderr_chunks: List[str] = []

        async def read_stream(stream, chunks: List[str]):
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace")
                chunks.append(text)
                if on_output:
                    try:
                        on_output(text)
                    except Exception:
                        pass

        try:
            await asyncio.wait_for(
                asyncio.gather(
                    read_stream(proc.stdout, stdout_chunks),
                    read_stream(proc.stderr, stderr_chunks),
                ),
                timeout=timeout,
            )
            await proc.wait()
        except asyncio.TimeoutError:
            kill_proc_tree(proc.pid)
            return False, f"Command timed out after {timeout} seconds.", {"returncode": -1}
        finally:
            if session_id and session_id in active_processes:
                active_processes.pop(session_id, None)

        exit_code = proc.returncode
        stdout = "".join(stdout_chunks)
        stderr = "".join(stderr_chunks)
        combined = stdout + ("\nSTDERR:\n" + stderr if stderr else "")

        # Truncate output if excessive
        trunc_notice = ""
        lines = combined.splitlines()
        if len(lines) > MAX_OUTPUT_LINES:
            combined = "\n".join(lines[:MAX_OUTPUT_LINES])
            trunc_notice = f"\n(Output truncated: {len(lines)} lines cut to {MAX_OUTPUT_LINES})"
        if len(combined.encode("utf-8")) > MAX_OUTPUT_BYTES:
            combined = combined[:MAX_OUTPUT_BYTES]
            trunc_notice = f"\n(Output truncated: exceeded {MAX_OUTPUT_BYTES} bytes)"

        success = (exit_code == 0)
        status_msg = f"Command exited with code {exit_code}."
        full_res = f"{status_msg}\n{combined}{trunc_notice}".strip()
        wrapped = wrap_untrusted_data(full_res, data_type="command_output", source=command)

        return success, wrapped, {"returncode": exit_code, "output": combined}

    except Exception as exc:
        return False, f"Execution failed: {exc}", {}


def kill_proc_tree(pid: int) -> None:
    """Kill process and all child processes cleanly."""
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], check=False, capture_output=True)
        else:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
    except Exception:
        pass


def stop_session_process(session_id: str) -> bool:
    """Kill running command process associated with a session."""
    proc = active_processes.get(session_id)
    if proc and proc.pid:
        kill_proc_tree(proc.pid)
        active_processes.pop(session_id, None)
        return True
    return False
