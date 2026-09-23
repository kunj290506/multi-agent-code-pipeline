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
OLLAMA_MODEL   : Ollama model   (default: qwen3-coder:latest)
"""

from __future__ import annotations

import os
import time
from pathlib import Path
import concurrent.futures
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

LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "ollama").lower()

GROQ_API_KEY: str  = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL: str    = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")

OLLAMA_BASE_URL: str   = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL: str      = os.getenv("OLLAMA_MODEL", "qwen3-coder:latest")
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

_groq_client = None

def call_groq(
    prompt: str,
    *,
    model: str | None = None,
    temperature: float = 0.1,
    max_tokens: int = 8000,
    timeout: int = 120,
) -> LLMResult:
    """Send a prompt to the Groq chat-completions API."""
    global _groq_client
    if _groq_client is None:
        from groq import Groq  # lazy import — not needed for Ollama-only runs
        if not GROQ_API_KEY:
            raise RuntimeError(
                "GROQ_API_KEY is not set. "
                "Export it in your environment before starting the services."
            )
        _groq_client = Groq(api_key=GROQ_API_KEY, timeout=timeout)

    # Use a faster default model if the placeholder is still used
    _model = model or GROQ_MODEL

    from groq import RateLimitError, InternalServerError
    t0 = time.monotonic()
    
    max_retries = 5
    for attempt in range(max_retries):
        try:
            response = _groq_client.chat.completions.create(
                model=_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            break
        except (RateLimitError, InternalServerError) as e:
            if attempt == max_retries - 1:
                raise
            # Exponential backoff: 2s, 4s, 8s, 16s...
            sleep_time = 2 ** attempt * 2
            print(f"[WARN] Groq rate limit/server error on attempt {attempt+1}. Retrying in {sleep_time}s... Error: {e}")
            time.sleep(sleep_time)

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
    max_tokens: int = 800,
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
    max_tokens: int = 8000,
    context_size: int | None = None,
    timeout: int = 600,
) -> LLMResult:
    """Route to the correct backend using Concurrent Hedged Requests.

    Uses LLM_PROVIDER env var (default: groq).
    If provider="groq", simultaneously dispatches to Groq and Ollama.
    The first to return a valid (non-empty) response wins, eliminating stalls.
    """
    _provider = (provider or LLM_PROVIDER).lower()
    
    if _provider != "groq":
        return call_ollama(
            prompt,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            context_size=context_size,
            timeout=timeout,
        )

    # Hedged Request Logic
    def run_groq():
        res = call_groq(prompt, model=model, temperature=temperature, max_tokens=max_tokens, timeout=min(timeout, 120))
        if not res.text.strip():
            raise ValueError("Empty response from Groq")
        return res

    def run_ollama():
        res = call_ollama(prompt, model=None, temperature=temperature, max_tokens=max_tokens, context_size=context_size, timeout=timeout)
        if not res.text.strip():
            raise ValueError("Empty response from Ollama")
        return res

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        future_groq = executor.submit(run_groq)
        future_ollama = executor.submit(run_ollama)

        futures = [future_groq, future_ollama]
        
        while futures:
            done, not_done = concurrent.futures.wait(futures, return_when=concurrent.futures.FIRST_COMPLETED)
            
            for future in done:
                try:
                    result = future.result()
                    return result  # First successful result wins
                except Exception as e:
                    print(f"[WARN] Hedged LLM task failed: {e}")
                    
            futures = list(not_done)
            
    # If both fail, fallback to a final synchronous Ollama attempt or raise
    print("[ERROR] Both hedged LLM tasks failed. Final fallback attempt...")
    return call_ollama(prompt, model=None, temperature=temperature, max_tokens=max_tokens, context_size=context_size, timeout=timeout)
