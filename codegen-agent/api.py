"""
Code-Gen Agent -- FastAPI HTTP Wrapper.

Exposes code-generation functionality over HTTP for the n8n workflow
and inter-agent communication.

Endpoints:
    POST /generate       -- Generate a code artifact from a specification.
    GET  /health         -- Liveness / readiness probe.
    GET  /spec-schema    -- Return the expected input specification schema.
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, model_validator

import config
import generator
from spec_schema import ArtifactSpec, GeneratedArtifact

app = FastAPI(
    title="Code-Gen Agent API",
    description=(
        "Generates code artifacts (REST endpoints, React components, etc.) "
        "from structured specifications using a local LLM."
    ),
    version="1.0.0",
)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class GenerateRequest(BaseModel):
    """Request body for the /generate endpoint."""
    spec: ArtifactSpec | None = Field(
        default=None, description="The artifact specification."
    )
    description: str | None = Field(
        default=None, description="Alias for spec.description (from Planner)."
    )
    context: str | None = Field(
        default=None, description="Optional context."
    )
    offline: bool = Field(
        default=False,
        description="If true, use offline mode (no Ollama required).",
    )

    @model_validator(mode="before")
    @classmethod
    def check_spec_or_description(cls, data: dict):
        if not data.get("spec") and data.get("description"):
            data["spec"] = {
                "artifact_type": "unknown",
                "name": "GeneratedComponent",
                "description": data["description"],
                "context": data.get("context", "")
            }
        if not data.get("spec"):
            raise ValueError("Either 'spec' or 'description' must be provided.")
        return data


class GenerateResponse(BaseModel):
    """Response body for the /generate endpoint."""
    success: bool
    artifact: GeneratedArtifact
    mode: str = Field(
        ..., description="'online' or 'offline'."
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health_check():
    """Return service health status."""
    return {"status": "healthy", "service": "codegen-agent"}


@app.get("/spec-schema")
def get_spec_schema():
    """Return the expected input specification schema as JSON Schema."""
    return {
        "input_schema": ArtifactSpec.model_json_schema(),
        "output_schema": GeneratedArtifact.model_json_schema(),
    }


@app.post("/generate", response_model=GenerateResponse)
def generate(request: GenerateRequest):
    """Generate a code artifact from the provided specification."""
    try:
        if request.offline:
            artifact = generator.generate_artifact_offline(request.spec)
            mode = "offline"
        else:
            artifact = generator.generate_artifact(request.spec)
            mode = "online"

        return GenerateResponse(
            success=True,
            artifact=artifact,
            mode=mode,
        )
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
