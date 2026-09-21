"""
Shared LLM dispatch layer — Groq-first.

Default backend is Groq (qwen/qwen3.8-27b).
Set LLM_PROVIDER=ollama to use a local Ollama server instead.

Environment variables
---------------------
LLM_PROVIDER   : "groq" (default) | "ollama"
GROQ_API_KEY   : Groq API key (required for groq provider)
GROQ_MODEL     : Groq model id  (default: qwen/qwen3.8-27b)
OLLAMA_BASE_URL: Ollama server  (default: http://localhost:11434)
OLLAMA_MODEL   : Ollama model   (default: qwen2.5:3b-instruct-q4_K_M)
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
    # Search for .env from current dir up to 3 parent directories
    load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
    load_dotenv()
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Configuration — read from environment
# ---------------------------------------------------------------------------

LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "groq").lower()

GROQ_API_KEY: str  = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL: str    = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")

OLLAMA_BASE_URL: str   = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL: str      = os.getenv("OLLAMA_MODEL", "qwen2.5:3b-instruct-q4_K_M")
OLLAMA_KEEP_ALIVE: str = os.getenv("OLLAMA_KEEP_ALIVE", "30m")
OLLAMA_CONTEXT_SIZE: int = int(os.getenv("OLLAMA_CONTEXT_SIZE", "2048"))


# ---------------------------------------------------------------------------
# Normalised return type
# ---------------------------------------------------------------------------

class LLMResult:
    """Uniform result from any LLM backend."""

    __slots__ = ("text", "provider", "model", "duration_ms", "schema_errors")

    def __init__(
        self,
        text: str,
        provider: str,
        model: str,
        duration_ms: int,
        schema_errors: list[str] | None = None,
    ) -> None:
        self.text = text
        self.provider = provider
        self.model = model
        self.duration_ms = duration_ms
        self.schema_errors: list[str] = schema_errors or []


# ---------------------------------------------------------------------------
# Groq backend (default)
# ---------------------------------------------------------------------------

def call_groq(
    prompt: str,
    *,
    model: str | None = None,
    temperature: float = 0.1,
    max_tokens: int = 1024,
    timeout: int = 120,
) -> LLMResult:
    """Send a prompt to the Groq chat-completions API."""
    from groq import Groq  # lazy import — not needed for Ollama-only runs

    _model = model or GROQ_MODEL
    api_key = GROQ_API_KEY or os.getenv("GROQ_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY is not set. "
            "Export it in your environment before starting the services."
        )
    client = Groq(api_key=api_key, timeout=timeout)
    t0 = time.monotonic()
    response = client.chat.completions.create(
        model=_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    duration_ms = int((time.monotonic() - t0) * 1000)
    text = response.choices[0].message.content or ""
    return LLMResult(text=text, provider="groq", model=_model, duration_ms=duration_ms)


# ---------------------------------------------------------------------------
# Ollama backend (fallback / local dev)
# ---------------------------------------------------------------------------

def call_ollama(
    prompt: str,
    *,
    model: str | None = None,
    temperature: float = 0.1,
    max_tokens: int = 1024,
    context_size: int | None = None,
    timeout: int = 600,
) -> LLMResult:
    """Send a prompt to the local Ollama /api/generate endpoint."""
    import requests

    _model = model or OLLAMA_MODEL
    payload: dict[str, Any] = {
        "model": _model,
        "prompt": prompt,
        "stream": False,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
            "num_ctx": context_size or OLLAMA_CONTEXT_SIZE,
        },
    }
    t0 = time.monotonic()
    resp = requests.post(
        f"{OLLAMA_BASE_URL}/api/generate",
        json=payload,
        timeout=timeout,
    )
    resp.raise_for_status()
    duration_ms = int((time.monotonic() - t0) * 1000)
    text = resp.json().get("response", "")
    return LLMResult(text=text, provider="ollama", model=_model, duration_ms=duration_ms)


# ---------------------------------------------------------------------------
# Unified dispatch
# ---------------------------------------------------------------------------

def call_llm(
    prompt: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    temperature: float = 0.1,
    max_tokens: int = 1024,
    context_size: int | None = None,
    timeout: int = 600,
) -> LLMResult:
    """Route to the correct backend.

    Uses LLM_PROVIDER env var (default: groq).
    Pass provider= explicitly to override per-call.
    """
    _provider = (provider or LLM_PROVIDER).lower()
    if _provider == "groq":
        return call_groq(
            prompt,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=min(timeout, 120),
        )
    return call_ollama(
        prompt,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        context_size=context_size,
        timeout=timeout,
    )
