"""
Code-Gen Agent Configuration.

Centralizes all configurable parameters for the code generation service.
"""

import os

# ---------------------------------------------------------------------------
# Ollama LLM settings
# ---------------------------------------------------------------------------
OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct-q4_K_M")
GROQ_MODEL = os.getenv(
	"CODEGEN_GROQ_MODEL", os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
)

# ---------------------------------------------------------------------------
# LLM generation parameters
# ---------------------------------------------------------------------------
TEMPERATURE: float = float(os.getenv("CODEGEN_TEMPERATURE", "0.2"))
MAX_TOKENS: int = int(os.getenv("CODEGEN_MAX_TOKENS", "4096"))
OLLAMA_KEEP_ALIVE: str = os.getenv("OLLAMA_KEEP_ALIVE", "-1")
OLLAMA_CONTEXT_SIZE: int = int(os.getenv("OLLAMA_CONTEXT_SIZE", "4096"))

# ---------------------------------------------------------------------------
# API server
# ---------------------------------------------------------------------------
API_HOST: str = os.getenv("CODEGEN_HOST", "0.0.0.0")
API_PORT: int = int(os.getenv("CODEGEN_PORT", "8014"))
