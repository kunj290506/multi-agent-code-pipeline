"""
DB Agent -- Execution Layer FastAPI HTTP Wrapper.

Exposes query-execution functionality over HTTP. This API runs on a
separate port (8003) from the query-generation API (8002).

Endpoints:
    POST /execute    -- Execute a parameterized query in a sandbox.
    GET  /health     -- Liveness / readiness probe.
"""

import os

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Any

app = FastAPI(
    title="DB Agent -- Execution Layer API",
    description=(
        "Executes parameterized SQL queries against an isolated, sandboxed "
        "database with built-in protections (timeouts, row limits, "
        "read-only enforcement)."
    ),
    version="1.0.0",
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

EXECUTOR_HOST: str = os.getenv("DB_EXECUTOR_HOST", "0.0.0.0")
EXECUTOR_PORT: int = int(os.getenv("DB_EXECUTOR_PORT", "8013"))


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class ExecuteRequest(BaseModel):
    """Request body for the /execute endpoint."""
    query: str = Field(
        ..., description="The SQL query to execute (use ? for parameters)."
    )
    parameters: list[Any] = Field(
        default_factory=list,
        description="Ordered list of parameter values for the query.",
    )
    timeout: float = Field(
        default=10.0,
        ge=0.1,
        le=60.0,
        description="Maximum execution time in seconds (0.1 to 60).",
    )
    max_rows: int = Field(
        default=1000,
        ge=1,
        le=10000,
        description="Maximum number of rows to return (1 to 10000).",
    )
    enforce_read_only: bool | None = Field(
        default=None,
        description=(
            "If True, use a read-only connection. "
            "If None, auto-detect based on query type."
        ),
    )


class ExecuteResponse(BaseModel):
    """Response body for the /execute endpoint."""
    success: bool
    query: str
    parameters: list[Any]
    columns: list[str] = []
    rows: list[dict] = []
    row_count: int = 0
    truncated: bool = False
    execution_time_ms: float = 0.0
    error: str | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health_check():
    """Return service health status."""
    return {"status": "healthy", "service": "db-agent-executor"}


@app.post("/execute", response_model=ExecuteResponse)
def execute(request: ExecuteRequest):
    """Execute a parameterized query in a sandboxed database."""
    # Import here to avoid circular imports and keep the module loadable
    # even if executor dependencies are not fully available.
    import executor

    try:
        result = executor.execute_query(
            query=request.query,
            parameters=request.parameters,
            timeout=request.timeout,
            max_rows=request.max_rows,
            enforce_read_only=request.enforce_read_only,
        )
        return ExecuteResponse(**result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "executor_api:app",
        host=EXECUTOR_HOST,
        port=EXECUTOR_PORT,
        reload=True,
    )
