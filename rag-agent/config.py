"""
RAG Agent Configuration.

Centralizes all configurable parameters for the ingestion pipeline,
vector store, embedding model, and LLM inference endpoint.
"""

import os

# ---------------------------------------------------------------------------
# Ollama LLM settings
# ---------------------------------------------------------------------------
OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct-q4_K_M")

# ---------------------------------------------------------------------------
# Embedding model (runs locally via sentence-transformers)
# ---------------------------------------------------------------------------
EMBEDDING_MODEL_NAME: str = os.getenv(
    "EMBEDDING_MODEL", "all-MiniLM-L6-v2"
)

# ---------------------------------------------------------------------------
# ChromaDB vector store
# ---------------------------------------------------------------------------
CHROMA_PERSIST_DIR: str = os.getenv(
    "CHROMA_PERSIST_DIR",
    os.path.join(os.path.dirname(__file__), ".chroma_store"),
)
CHROMA_COLLECTION_NAME: str = os.getenv(
    "CHROMA_COLLECTION", "codebase_docs"
)

# ---------------------------------------------------------------------------
# Document ingestion
# ---------------------------------------------------------------------------
# Default directory to ingest source code and documentation from.
DEFAULT_SOURCE_DIR: str = os.getenv(
    "RAG_SOURCE_DIR",
    os.path.join(os.path.dirname(__file__), "..", "target-app"),
)

# File extensions to include during ingestion.
SUPPORTED_EXTENSIONS: list[str] = [
    ".py", ".js", ".ts", ".jsx", ".tsx",
    ".md", ".txt", ".rst",
    ".json", ".yaml", ".yml",
    ".html", ".css",
    ".sql",
]

# Text splitting parameters.
CHUNK_SIZE: int = int(os.getenv("CHUNK_SIZE", "1000"))
CHUNK_OVERLAP: int = int(os.getenv("CHUNK_OVERLAP", "200"))

# ---------------------------------------------------------------------------
# API server
# ---------------------------------------------------------------------------
API_HOST: str = os.getenv("RAG_API_HOST", "0.0.0.0")
API_PORT: int = int(os.getenv("RAG_API_PORT", "8001"))
