"""
RAG Agent -- FastAPI HTTP Wrapper.

Exposes the ingestion and query functionality over HTTP so the n8n
orchestration workflow (or any other agent) can invoke it.

Endpoints:
    POST /ingest     -- Trigger document ingestion from a source directory.
    POST /query      -- Ask a natural-language question against the vector store.
    GET  /health     -- Liveness / readiness probe.
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, model_validator

import config
import ingest as ingest_module
import query as query_module

app = FastAPI(
    title="RAG Agent API",
    description="Retrieval-Augmented Generation agent for the multi-agent code pipeline.",
    version="1.0.0",
)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class IngestRequest(BaseModel):
    """Request body for the /ingest endpoint."""
    source_dir: str = Field(
        default=None,
        description="Path to the directory to ingest. Defaults to target-app/.",
    )


class IngestResponse(BaseModel):
    """Response body for the /ingest endpoint."""
    status: str
    files_found: int = 0
    chunks_stored: int = 0
    message: str = ""


class QueryRequest(BaseModel):
    """Request body for the /query endpoint."""
    question: str | None = Field(default=None, description="Natural-language question.")
    description: str | None = Field(default=None, description="Alias for question (from Planner).")
    top_k: int = Field(default=5, ge=1, le=20, description="Number of chunks to retrieve.")

    @model_validator(mode="before")
    @classmethod
    def check_question_or_description(cls, data: dict):
        if not data.get("question") and data.get("description"):
            data["question"] = data["description"]
        if not data.get("question"):
            raise ValueError("Either 'question' or 'description' must be provided.")
        return data


class QueryResponse(BaseModel):
    """Response body for the /query endpoint."""
    question: str
    answer: str
    sources: list[str]
    num_chunks_used: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health_check():
    """Return service health status."""
    return {"status": "healthy", "service": "rag-agent"}


@app.post("/ingest", response_model=IngestResponse)
def ingest_documents(request: IngestRequest):
    """Ingest documents from the specified source directory into ChromaDB."""
    try:
        source_dir = request.source_dir or config.DEFAULT_SOURCE_DIR
        documents = ingest_module.collect_documents(source_dir)
        if not documents:
            return IngestResponse(
                status="warning",
                files_found=0,
                chunks_stored=0,
                message="No documents found in the source directory.",
            )

        texts, metadatas = ingest_module.chunk_documents(documents)
        ingest_module.build_vector_store(texts, metadatas)

        return IngestResponse(
            status="success",
            files_found=len(documents),
            chunks_stored=len(texts),
            message=f"Ingested {len(documents)} files into {len(texts)} chunks.",
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/query", response_model=QueryResponse)
def query_documents(request: QueryRequest):
    """Answer a natural-language question using RAG."""
    try:
        result = query_module.query(request.question, top_k=request.top_k)
        return QueryResponse(**result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api:app",
        host=config.API_HOST,
        port=config.API_PORT,
        reload=True,
    )
