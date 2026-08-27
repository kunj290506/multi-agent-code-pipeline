"""
Planner Agent Configuration.

Centralizes all configurable parameters for the planner/orchestrator agent.
"""

import os

# ---------------------------------------------------------------------------
# Ollama LLM settings
# ---------------------------------------------------------------------------
OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct-q4_K_M")

# ---------------------------------------------------------------------------
# Subtask schema: valid agent names
# ---------------------------------------------------------------------------
VALID_AGENTS: list[str] = [
    "rag-agent",
    "codegen-agent",
    "reviewer-agent",
    "db-agent",
]

# ---------------------------------------------------------------------------
# LLM generation parameters
# ---------------------------------------------------------------------------
TEMPERATURE: float = float(os.getenv("PLANNER_TEMPERATURE", "0.1"))
MAX_TOKENS: int = int(os.getenv("PLANNER_MAX_TOKENS", "2048"))

# ---------------------------------------------------------------------------
# API server
# ---------------------------------------------------------------------------
API_HOST: str = os.getenv("PLANNER_API_HOST", "0.0.0.0")
API_PORT: int = int(os.getenv("PLANNER_API_PORT", "8000"))
