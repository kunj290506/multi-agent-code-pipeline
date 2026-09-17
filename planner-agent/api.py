"""
Planner Agent -- FastAPI HTTP Wrapper.

Exposes the task decomposition functionality over HTTP so the n8n
orchestration workflow can invoke it.

Endpoints:
    POST /plan       -- Decompose a feature request into subtasks.
    GET  /health     -- Liveness / readiness probe.
    GET  /schema     -- Return the expected output JSON schema.
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

import config
import planner

app = FastAPI(
    title="Planner Agent API",
    description="Orchestrator agent that decomposes feature requests into subtasks.",
    version="1.0.0",
)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class PlanRequest(BaseModel):
    """Request body for the /plan endpoint."""
    feature_request: str = Field(
        ..., description="Plain-language feature request to decompose."
    )
    offline: bool = Field(
        default=False,
        description="If true, use offline mode (no Ollama required).",
    )


class SubtaskResponse(BaseModel):
    """Schema for a single subtask in the plan."""
    task_id: str
    agent: str
    description: str
    dependencies: list[str]
    target_filename: str | None = None


class PlanResponse(BaseModel):
    """Response body for the /plan endpoint."""
    feature_request: str
    subtasks: list[SubtaskResponse]
    reasoning: str | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health_check():
    """Return service health status."""
    return {"status": "healthy", "service": "planner-agent"}


@app.get("/schema")
def get_schema():
    """Return the JSON schema that plan responses conform to."""
    return planner.PLAN_SCHEMA


@app.post("/plan", response_model=PlanResponse)
def create_plan(request: PlanRequest):
    """Decompose a feature request into an ordered list of subtasks."""
    try:
        if request.offline:
            plan = planner.decompose_offline(request.feature_request)
        else:
            plan = planner.decompose(request.feature_request)
        return PlanResponse(**plan)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
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
