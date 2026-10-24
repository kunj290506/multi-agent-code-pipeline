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


async def check_ollama_health() -> Tuple[bool, List[str]]:
    """Check if Ollama server is up and list available models."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            if resp.status_code == 200:
                data = resp.json()
                models = [m.get("name") for m in data.get("models", []) if m.get("name")]
                return True, models
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
            "temperature": temperature,
        },
    }

    if tools and not fallback_json:
        payload["tools"] = tools

    full_content = ""
    collected_tool_calls: List[Dict[str, Any]] = []

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
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
        logger.error(f"Error streaming from Ollama: {exc}")
        yield {"type": "error", "message": f"Connection to Ollama failed: {str(exc)}"}
        return

    # If no native tool calls were emitted and fallback_json is requested or possible:
    if not collected_tool_calls and tools:
        # Check if full_content contains JSON-action protocol:
        parsed_call = extract_json_action(full_content)
        if parsed_call:
            yield {"type": "tool_call", "tool_call": parsed_call}

    yield {"type": "done", "total_content": full_content}


def extract_json_action(text: str) -> Optional[Dict[str, Any]]:
    """Parse JSON action from text if model emitted JSON format."""
    patterns = [
        r"```json\s*(\{[\s\S]*?\})\s*```",
        r"```\s*(\{[\s\S]*?\})\s*```",
        r"(\{\s*\"(?:action|name|tool)\"\s*:\s*\"[^\"]+\"[\s\S]*?\})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            candidate = match.group(1).strip()
            try:
                data = json.loads(candidate)
                action = data.get("action") or data.get("name") or data.get("tool")
                args = data.get("arguments") or data.get("args") or data.get("parameters") or {}
                if action and isinstance(args, dict):
                    call_id = f"fallback_{int(time.time()*1000)}"
                    return {"name": action, "arguments": args, "id": call_id}
            except Exception:
                continue
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
