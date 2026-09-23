"""
Code-Gen Agent Configuration.

Centralizes all configurable parameters for the code generation service.
"""

import os

# ---------------------------------------------------------------------------
# Ollama LLM settings
# ---------------------------------------------------------------------------
OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen3-coder:latest")
GROQ_MODEL = os.getenv(
	"CODEGEN_GROQ_MODEL", os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")
)

# ---------------------------------------------------------------------------
# LLM generation parameters
# ---------------------------------------------------------------------------
TEMPERATURE: float = float(os.getenv("CODEGEN_TEMPERATURE", "0.2"))
MAX_TOKENS: int = int(os.getenv("CODEGEN_MAX_TOKENS", "4096"))
OLLAMA_KEEP_ALIVE: str = os.getenv("OLLAMA_KEEP_ALIVE", "30m")
OLLAMA_CONTEXT_SIZE: int = int(os.getenv("OLLAMA_CONTEXT_SIZE", "2048"))

# ---------------------------------------------------------------------------
# API server
# ---------------------------------------------------------------------------
API_HOST: str = os.getenv("CODEGEN_HOST", "0.0.0.0")
API_PORT: int = int(os.getenv("CODEGEN_PORT", "8014"))
