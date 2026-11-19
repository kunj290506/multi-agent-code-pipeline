# backend/llm.py
"""Ollama client with streaming and tool support, with fallback JSON-action protocol."""

import json
import logging
import os
import re
import time
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger("backend.llm")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "qwen2.5:7b-instruct-q4_K_M")
NUM_CTX = int(os.environ.get("NUM_CTX", "8192"))


EMBEDDING_MODEL_HINTS = ("embed", "nomic-embed", "mxbai-embed", "bge-", "all-minilm")


def is_chat_model(name: str) -> bool:
    low = name.lower()
    return not any(h in low for h in EMBEDDING_MODEL_HINTS)


async def check_ollama_health() -> Tuple[bool, List[str]]:
    """Check if Ollama server is up and list available chat/coding models."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            if resp.status_code == 200:
                data = resp.json()
                all_models = [m.get("name") for m in data.get("models", []) if m.get("name")]
                chat_models = [m for m in all_models if is_chat_model(m)]
                return True, chat_models or all_models
    except Exception as exc:
        logger.warning(f"Ollama health check failed: {exc}")
    return False, []


async def stream_chat(
    model: str,
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    num_ctx: int = NUM_CTX,
    temperature: float = 0.2,
    fallback_json: bool = False,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Stream chat completion from Ollama.
    Yields events:
      {"type": "token", "content": "..."}
      {"type": "tool_call", "tool_call": {"name": "...", "arguments": {...}, "id": "..."}}
      {"type": "done", "total_content": "..."}
    """
    url = f"{OLLAMA_BASE_URL}/api/chat"
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
        "options": {
            "num_ctx": num_ctx,
            "num_predict": 4096,
            "temperature": temperature,
        },
    }

    if tools and not fallback_json:
        payload["tools"] = tools

    full_content = ""
    collected_tool_calls: List[Dict[str, Any]] = []

    try:
        timeout_cfg = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)
        async with httpx.AsyncClient(timeout=timeout_cfg) as client:
            async with client.stream("POST", url, json=payload) as response:
                if response.status_code != 200:
                    err_text = await response.aread()
                    logger.error(f"Ollama returned HTTP {response.status_code}: {err_text.decode('utf-8', 'ignore')}")
                    yield {"type": "error", "message": f"Ollama error ({response.status_code}): {err_text.decode('utf-8', 'ignore')}"}
                    return

                async for line in response.aiter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except Exception:
                        continue

                    msg = chunk.get("message", {})
                    token = msg.get("content", "")
                    if token:
                        full_content += token
                        yield {"type": "token", "content": token}

                    # Check for native Ollama tool calls
                    tool_calls = msg.get("tool_calls", [])
                    if tool_calls:
                        for tc in tool_calls:
                            func = tc.get("function", {})
                            name = func.get("name")
                            args = func.get("arguments", {})
                            if isinstance(args, str):
                                try:
                                    args = json.loads(args)
                                except Exception:
                                    pass
                            call_id = tc.get("id") or f"call_{len(collected_tool_calls)}"
                            call_item = {"name": name, "arguments": args, "id": call_id}
                            collected_tool_calls.append(call_item)
                            yield {"type": "tool_call", "tool_call": call_item}

                    if chunk.get("done"):
                        break

    except Exception as exc:
        err_detail = str(exc).strip() or type(exc).__name__
        logger.error(f"Error streaming from Ollama: {err_detail}")
        yield {"type": "error", "message": f"Connection to Ollama failed ({err_detail}). Try a faster model like qwen2.5-coder:3b or retry."}
        return

    # If no native tool calls were emitted and fallback_json is requested or possible:
    if not collected_tool_calls and tools:
        # Check if full_content contains JSON-action protocol:
        parsed_call = extract_json_action(full_content)
        if parsed_call:
            yield {"type": "tool_call", "tool_call": parsed_call}

    yield {"type": "done", "total_content": full_content}


def _repair_json_escapes(raw: str) -> str:
    """Fix invalid backslash escapes and preserve JS regex \\/ escapes inside JSON tool-call strings."""
    # 1. Preserve JS regex \/ escapes (e.g. /\\+|\\-|\\*|\\/|\\./ or /[+\\-*\\/]/), while leaving <\\/tag> and http:\\/\\/ alone
    fixed = re.sub(r'(?<!https:)(?<!http:)(?<![\\<:])\\/(?=[|\]/.+*?\\^$()])', r'\\\\/', raw)
    # 2. Escape backslashes NOT followed by a valid JSON escape char (" \ / b f n r t u)
    fixed = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', fixed)
    return fixed


def _try_parse_action_dict(candidate: str) -> Optional[Dict[str, Any]]:
    # Try repaired first if it contains JS regex \/ patterns so json.loads doesn't silently eat \/ into /
    attempts = (_repair_json_escapes(candidate), candidate)
    for attempt in attempts:
        try:
            data = json.loads(attempt)
            if isinstance(data, dict):
                action = data.get("action") or data.get("name") or data.get("tool")
                args = data.get("arguments") or data.get("args") or data.get("parameters")
                if action and isinstance(args, dict):
                    return {"name": action, "arguments": args, "id": f"fallback_{int(time.time()*1000)}"}
        except Exception:
            pass
    return None


def extract_json_action(text: str) -> Optional[Dict[str, Any]]:
    """Parse JSON tool action from text using a balanced JSON decoder (handles nested CSS/JS braces and regex escapes)."""
    if not text or "{" not in text:
        return None

    decoder = json.JSONDecoder()
    # Try fenced JSON blocks first
    for block_match in re.finditer(r"```(?:json)?\s*([\s\S]*?)```", text):
        block = block_match.group(1).strip()
        if not block.startswith("{"):
            continue
        parsed = _try_parse_action_dict(block)
        if parsed:
            return parsed

    # Fallback: scan every '{' using JSONDecoder.raw_decode (repaired first so JS regex \/ is preserved)
    for source_text in (_repair_json_escapes(text), text):
        idx = 0
        length = len(source_text)
        while idx < length:
            brace_pos = source_text.find("{", idx)
            if brace_pos == -1:
                break
            try:
                data, end_pos = decoder.raw_decode(source_text, brace_pos)
                if isinstance(data, dict):
                    action = data.get("action") or data.get("name") or data.get("tool")
                    args = data.get("arguments") or data.get("args") or data.get("parameters")
                    if action and isinstance(args, dict):
                        return {"name": action, "arguments": args, "id": f"fallback_{int(time.time()*1000)}"}
                idx = end_pos
            except Exception:
                idx = brace_pos + 1
    return None


async def generate_single(
    model: str,
    prompt: str,
    system: Optional[str] = None,
    num_ctx: int = 4096,
) -> str:
    """Non-streaming single prompt response from Ollama (used for summaries / internal LLM)."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    url = f"{OLLAMA_BASE_URL}/api/chat"
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "num_ctx": num_ctx,
            "temperature": 0.2,
        },
    }
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("message", {}).get("content", "").strip()
    except Exception as exc:
        logger.warning(f"generate_single failed: {exc}")
    return ""
