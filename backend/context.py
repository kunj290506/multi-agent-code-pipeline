# backend/context.py
"""Context builder, workspace summarizer, history trimmer, and codebase indexer."""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from llm import NUM_CTX, generate_single
from prompts import SYSTEM_PROMPT
from safety import MAX_READ_BYTES, wrap_untrusted_data
from store import search_keyword_index, upsert_code_chunks

KEY_CONFIG_FILES = {
    "package.json",
    "requirements.txt",
    "pyproject.toml",
    "setup.py",
    "tsconfig.json",
    "vite.config.ts",
    "vite.config.js",
    "docker-compose.yml",
    "Dockerfile",
    "Makefile",
    "README.md",
}


def estimate_tokens(text: str) -> int:
    """Approximate token count: characters divided by 4."""
    return max(1, len(text) // 4)


def get_workspace_summary(workspace_root: str, max_depth: int = 2) -> str:
    """Generate top-level directory tree up to max_depth and list key config files."""
    if not workspace_root or not os.path.isdir(workspace_root):
        return "(Workspace directory not found)"

    ws_real = os.path.realpath(workspace_root)
    ignored = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next", ".cache"}
    tree_lines = []
    found_configs = []

    def scan(current_dir: str, current_depth: int, prefix: str = ""):
        if current_depth > max_depth:
            return
        try:
            entries = sorted(os.scandir(current_dir), key=lambda e: (not e.is_dir(), e.name.lower()))
            filtered = [e for e in entries if e.name not in ignored]
            for idx, entry in enumerate(filtered):
                is_last = (idx == len(filtered) - 1)
                connector = "└── " if is_last else "├── "
                rel_path = os.path.relpath(entry.path, ws_real)

                if entry.is_file() and entry.name in KEY_CONFIG_FILES:
                    found_configs.append(rel_path)

                if entry.is_dir():
                    tree_lines.append(f"{prefix}{connector}{entry.name}/")
                    sub_prefix = prefix + ("    " if is_last else "│   ")
                    scan(entry.path, current_depth + 1, sub_prefix)
                else:
                    if current_depth <= 2:
                        tree_lines.append(f"{prefix}{connector}{entry.name}")
        except Exception:
            pass

    tree_lines.append(f"Workspace: {os.path.basename(ws_real) or ws_real}")
    scan(ws_real, 1)

    summary = "\n".join(tree_lines[:40])
    if found_configs:
        summary += f"\n\nKey configuration files present: {', '.join(sorted(set(found_configs)))}"
    return summary


def extract_file_mentions(text: str, workspace_root: str) -> List[str]:
    """Find @file mentions in user message that exist inside workspace."""
    words = text.split()
    mentions = []
    ws_real = os.path.realpath(workspace_root)
    for word in words:
        if word.startswith("@") and len(word) > 1:
            raw_path = word[1:].strip(".,;:?!()[]{}\"'")
            candidate = os.path.realpath(os.path.join(ws_real, raw_path))
            try:
                if os.path.commonpath([ws_real, candidate]) == ws_real and os.path.isfile(candidate):
                    mentions.append(os.path.relpath(candidate, ws_real).replace("\\", "/"))
            except Exception:
                pass
    return sorted(set(mentions))


async def build_context(
    session_id: str,
    user_message: str,
    raw_history: List[Dict[str, Any]],
    workspace_root: str,
    model: str,
    recently_read_files: Optional[List[str]] = None,
    num_ctx: int = NUM_CTX,
    response_headroom: int = 2048,
) -> List[Dict[str, Any]]:
    """
    Build prompt messages within token budget:
    1. System prompt with workspace summary
    2. File context (@mentions and recently read files)
    3. Trimmed / summarized conversation history
    4. Current user prompt
    """
    token_budget = num_ctx - response_headroom
    ws_summary = get_workspace_summary(workspace_root)
    system_text = (
        f"{SYSTEM_PROMPT}\n\n"
        f"--- WORKSPACE CONTEXT ---\n"
        f"{ws_summary}\n"
        f"-------------------------"
    )

    # 1. Attached / Mentioned file snippets
    mentioned_files = extract_file_mentions(user_message, workspace_root)
    files_to_inject = list(dict.fromkeys(mentioned_files + (recently_read_files or [])))[:5]
    file_context_parts = []

    for f_rel in files_to_inject:
        f_abs = os.path.realpath(os.path.join(workspace_root, f_rel))
        if os.path.isfile(f_abs) and os.path.getsize(f_abs) <= MAX_READ_BYTES:
            try:
                with open(f_abs, "r", encoding="utf-8", errors="replace") as fh:
                    lines = fh.readlines()
                # Inject up to first 120 lines
                snippet = "".join([f"{idx:3d} | {ln}" for idx, ln in enumerate(lines[:120], start=1)])
                notice = f"\n... ({len(lines)-120} more lines omitted; use read_file for more)" if len(lines) > 120 else ""
                wrapped = wrap_untrusted_data(snippet + notice, data_type="attached_file", source=f_rel)
                file_context_parts.append(wrapped)
            except Exception:
                pass

    file_context_msg = ""
    if file_context_parts:
        file_context_msg = "Attached files and recently referenced code:\n" + "\n\n".join(file_context_parts)

    system_tokens = estimate_tokens(system_text)
    user_tokens = estimate_tokens(user_message)
    file_tokens = estimate_tokens(file_context_msg)

    remaining_budget = token_budget - (system_tokens + user_tokens + file_tokens)

    # Format history turns
    formatted_history: List[Dict[str, Any]] = []
    for item in raw_history:
        role = item.get("role", "user")
        content = item.get("content", "")
        formatted_history.append({"role": role, "content": content})

    # If history exceeds remaining budget, summarize older turns
    total_hist_tokens = sum(estimate_tokens(m["content"]) for m in formatted_history)
    if total_hist_tokens > remaining_budget and len(formatted_history) > 4:
        # Keep last 4 turns verbatim
        verbatim_turns = formatted_history[-4:]
        older_turns = formatted_history[:-4]
        older_text = "\n".join([f"{m['role']}: {m['content'][:300]}" for m in older_turns])

        # Summarize older turns
        summary_prompt = (
            "Summarize the following prior conversation between user and coding assistant in 3-4 sentences, "
            "focusing on what files were discussed, what changes were made, and current goals:\n\n"
            + older_text
        )
        summary = await generate_single(model, summary_prompt, system="You are an expert summarizer.")
        if not summary:
            summary = "Prior conversation covered initial task setup, requirements discussion, and file checks."

        formatted_history = [
            {"role": "system", "content": f"Summary of earlier conversation:\n{summary}"}
        ] + verbatim_turns

    # Assemble final message list
    messages: List[Dict[str, Any]] = [{"role": "system", "content": system_text}]
    if file_context_msg:
        messages.append({"role": "system", "content": file_context_msg})

    messages.extend(formatted_history)
    messages.append({"role": "user", "content": user_message})

    return messages


def index_workspace(workspace_root: str) -> int:
    """Build or update simple keyword chunk index for codebase."""
    if not workspace_root or not os.path.isdir(workspace_root):
        return 0

    ws_real = os.path.realpath(workspace_root)
    ignored = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
    indexed_count = 0

    for root, dirs, files in os.walk(ws_real):
        dirs[:] = [d for d in dirs if d not in ignored]
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in {".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".json", ".md", ".yaml", ".yml", ".sql"}:
                f_abs = os.path.join(root, f)
                rel_path = os.path.relpath(f_abs, ws_real).replace("\\", "/")
                try:
                    mtime = os.path.getmtime(f_abs)
                    size = os.path.getsize(f_abs)
                    if size > MAX_READ_BYTES:
                        continue
                    with open(f_abs, "r", encoding="utf-8", errors="ignore") as fh:
                        content = fh.read()
                    # Chunk by 50 lines
                    lines = content.splitlines()
                    chunks = []
                    for i in range(0, len(lines), 40):
                        chunk = "\n".join(lines[i:i + 50])
                        chunks.append(chunk)
                    upsert_code_chunks(rel_path, chunks, mtime)
                    indexed_count += 1
                except Exception:
                    continue
    return indexed_count
