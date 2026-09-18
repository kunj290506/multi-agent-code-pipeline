"""
DB Agent -- FastAPI HTTP Wrapper.

Exposes query-generation functionality over HTTP for the n8n workflow.
This service handles ONLY query generation -- execution is out of scope.

Endpoints:
    POST /generate   -- Generate a SQL query from natural language.
    POST /validate   -- Validate an existing SQL query for safety.
    GET  /health     -- Liveness / readiness probe.
    GET  /schema     -- Return the current database schema.
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, model_validator

import config
import query_generator

app = FastAPI(
    title="DB Agent API",
    description="Database query generation agent (NL-to-SQL). "
                "Execution and sandboxing are handled separately.",
    version="1.0.0",
)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class GenerateRequest(BaseModel):
    """Request body for the /generate endpoint."""
    request: str | None = Field(
        default=None, description="Natural-language description of the desired query."
    )
    description: str | None = Field(default=None, description="Alias for request (from Planner).")
    schema_override: str | None = Field(
        default=None,
        description="Optional database schema to use instead of the default.",
    )
    offline: bool = Field(
        default=False,
        description="If true, use offline mode (no Ollama required).",
    )

    @model_validator(mode="before")
    @classmethod
    def check_request_or_description(cls, data: dict):
        if not data.get("request") and data.get("description"):
            data["request"] = data["description"]
        if not data.get("request"):
            raise ValueError("Either 'request' or 'description' must be provided.")
        return data


class SafetyCheckResult(BaseModel):
    """Safety validation result."""
    passed: bool
    violations: list[str]


class GenerateResponse(BaseModel):
    """Response body for the /generate endpoint."""
    query: str
    parameters: list
    query_type: str
    explanation: str
    assumptions: list[str] = []
    safety_check: SafetyCheckResult
    reasoning: str | None = Field(
        default=None,
        description=(
            "Optional explanation of how the query was constructed — why particular "
            "tables/columns were chosen or safety rules applied. Produced by the LLM "
            "when online; null (never synthesized) when running in offline/heuristic mode."
        ),
    )


class ValidateRequest(BaseModel):
    """Request body for the /validate endpoint."""
    query: str = Field(..., description="SQL query to validate.")


class ValidateResponse(BaseModel):
    """Response body for the /validate endpoint."""
    query: str
    safety_check: SafetyCheckResult


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health_check():
    """Return service health status."""
    return {"status": "healthy", "service": "db-agent"}


@app.get("/schema")
def get_schema():
    """Return the current database schema used for query generation."""
    return {"schema": config.PLACEHOLDER_SCHEMA.strip()}


@app.post("/generate", response_model=GenerateResponse)
def generate(request: GenerateRequest):
    """Generate a SQL query from a natural-language request."""
    try:
        if request.offline:
            result = query_generator.generate_query_offline(request.request)
        else:
            result = query_generator.generate_query(
                request.request,
                schema=request.schema_override,
            )
        return GenerateResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/validate", response_model=ValidateResponse)
def validate(request: ValidateRequest):
    """Validate a SQL query for safety without executing it."""
    violations = query_generator.validate_query(request.query)
    return ValidateResponse(
        query=request.query,
        safety_check=SafetyCheckResult(
            passed=len(violations) == 0,
            violations=violations,
        ),
    )


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
