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

import threading
import collections
import requests
from requests.adapters import HTTPAdapter

LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "groq" if os.getenv("GROQ_API_KEY") else "ollama").lower()

GROQ_API_KEY: str  = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL: str    = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")

OLLAMA_BASE_URL: str   = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL: str      = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct-q4_K_M")
OLLAMA_KEEP_ALIVE: str = os.getenv("OLLAMA_KEEP_ALIVE", "-1")
OLLAMA_CONTEXT_SIZE: int = int(os.getenv("OLLAMA_CONTEXT_SIZE", "4096"))

# Connection pool for Ollama
_ollama_session = requests.Session()
_adapter = HTTPAdapter(pool_connections=10, pool_maxsize=20)
_ollama_session.mount("http://", _adapter)
_ollama_session.mount("https://", _adapter)

# In-memory prompt cache for repeated calls
_CACHE_LOCK = threading.Lock()
_PROMPT_CACHE: collections.OrderedDict[tuple[str, str, float], LLMResult] = collections.OrderedDict()
_MAX_CACHE_SIZE = 128


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
    max_tokens: int = 4096,
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

    # Groq free tier has a 1000 OTPM (output tokens per minute) limit on qwen3.8
    # Clamping expected max_tokens prevents 429 rate limit errors
    _max_tokens = min(max_tokens, 950) if "qwen" in _model.lower() else max_tokens

    from groq import RateLimitError, InternalServerError
    t0 = time.monotonic()
    
    max_retries = 5
    for attempt in range(max_retries):
        try:
            response = _groq_client.chat.completions.create(
                model=_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=_max_tokens,
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
    """Send a prompt to the local Ollama /api/generate endpoint with connection pooling."""
    _model = model or OLLAMA_MODEL
    keep_alive_val = -1 if str(OLLAMA_KEEP_ALIVE).strip() in ("-1", "none") else OLLAMA_KEEP_ALIVE
    payload: dict[str, Any] = {
        "model": _model,
        "prompt": prompt,
        "stream": False,
        "keep_alive": keep_alive_val,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
            "num_ctx": context_size or OLLAMA_CONTEXT_SIZE,
        },
    }
    t0 = time.monotonic()
    resp = _ollama_session.post(
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
    max_tokens: int = 4096,
    context_size: int | None = None,
    timeout: int = 600,
) -> LLMResult:
    """Route to the correct backend with in-memory caching and hedged requests."""
    cache_key = (prompt, str(model or ""), float(temperature))
    with _CACHE_LOCK:
        if cache_key in _PROMPT_CACHE:
            cached = _PROMPT_CACHE[cache_key]
            # Return cached result with 0ms duration
            return LLMResult(
                text=cached.text,
                provider=cached.provider,
                model=cached.model,
                duration_ms=0,
                schema_errors=cached.schema_errors,
            )

    result = _call_llm_internal(
        prompt,
        provider=provider,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        context_size=context_size,
        timeout=timeout,
    )

    with _CACHE_LOCK:
        if len(_PROMPT_CACHE) >= _MAX_CACHE_SIZE:
            _PROMPT_CACHE.popitem(last=False)
        _PROMPT_CACHE[cache_key] = result

    return result


def _call_llm_internal(
    prompt: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    temperature: float = 0.1,
    max_tokens: int = 4096,
    context_size: int | None = None,
    timeout: int = 600,
) -> LLMResult:
    """Dispatch to Groq or Ollama using Concurrent Hedged Requests."""
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
        errors = {}
        
        while futures:
            done, not_done = concurrent.futures.wait(futures, return_when=concurrent.futures.FIRST_COMPLETED)
            
            for future in done:
                try:
                    result = future.result()
                    return result  # First successful result wins
                except Exception as e:
                    name = "Groq" if future == future_groq else "Ollama"
                    errors[name] = e
                    print(f"[WARN] Hedged LLM task ({name}) failed: {e}")
                    
            futures = list(not_done)
            
    # If both fail, raise an error detailing what went wrong
    print(f"[ERROR] Both hedged LLM tasks failed. Groq: {errors.get('Groq')} | Ollama: {errors.get('Ollama')}")
    raise RuntimeError(f"All LLM backends failed. Groq error: {errors.get('Groq')}. Ollama error: {errors.get('Ollama')}")
