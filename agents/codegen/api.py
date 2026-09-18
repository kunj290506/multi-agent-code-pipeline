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

def _infer_spec_from_description(description: str, context: str = "") -> dict:
    """Infer artifact_type, language, and framework from a plain description string.

    Used when the Planner routes a codegen subtask without a full ArtifactSpec.
    Falls back to 'unknown'/python/fastapi for unrecognised patterns.
    """
    desc_lower = description.lower()

    if ".html" in desc_lower or ("html" in desc_lower and "index" in desc_lower):
        return {
            "artifact_type": "html_page",
            "name": "GeneratedPage",
            "description": description,
            "language": "html",
            "framework": "none",
            "context": context,
        }
    if ".css" in desc_lower or ("style" in desc_lower and "css" in desc_lower):
        return {
            "artifact_type": "stylesheet",
            "name": "GeneratedStylesheet",
            "description": description,
            "language": "css",
            "framework": "none",
            "context": context,
        }
    if ".js" in desc_lower or ("javascript" in desc_lower) or ("script" in desc_lower and "js" in desc_lower):
        return {
            "artifact_type": "script",
            "name": "GeneratedScript",
            "description": description,
            "language": "javascript",
            "framework": "none",
            "context": context,
        }
    if ".md" in desc_lower or "readme" in desc_lower or "markdown" in desc_lower:
        return {
            "artifact_type": "documentation",
            "name": "README",
            "description": description,
            "language": "markdown",
            "framework": "none",
            "context": context,
        }
    if ".sql" in desc_lower or "migration" in desc_lower or "database" in desc_lower:
        return {
            "artifact_type": "database_migration",
            "name": "GeneratedMigration",
            "description": description,
            "language": "sql",
            "framework": "none",
            "context": context,
        }
    # Default: generic Python artifact
    return {
        "artifact_type": "unknown",
        "name": "GeneratedComponent",
        "description": description,
        "language": "python",
        "framework": "fastapi",
        "context": context,
    }


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
    prior_issues: list[dict] | None = Field(
        default=None,
        description=(
            "Issues from a previous Reviewer verdict, forwarded on retry. "
            "Each issue dict has at minimum: severity, rule_id (or rule), message. "
            "Appended as constraints into the spec so the LLM avoids repeating the "
            "same mistakes."
        ),
    )
    offline: bool = Field(
        default=False,
        description="If true, use offline mode (no Ollama required).",
    )

    @model_validator(mode="before")
    @classmethod
    def check_spec_or_description(cls, data: dict):
        if not data.get("spec") and data.get("description"):
            data["spec"] = _infer_spec_from_description(
                data["description"],
                context=data.get("context", ""),
            )
        if not data.get("spec"):
            raise ValueError("Either 'spec' or 'description' must be provided.")

        # Forward prior_issues as constraints so the model knows what to fix.
        prior_issues = data.get("prior_issues")
        if prior_issues and isinstance(prior_issues, list):
            spec = data["spec"]
            if isinstance(spec, dict):
                existing = spec.get("constraints") or []
            else:
                # ArtifactSpec object — convert to dict subset
                existing = list(getattr(spec, "constraints", []))
                spec = spec.model_dump() if hasattr(spec, "model_dump") else dict(spec)
                data["spec"] = spec
            issue_constraints = [
                f"[{iss.get('severity', 'error').upper()}] "
                f"{iss.get('rule_id') or iss.get('rule', 'UNKNOWN')}: "
                f"{iss.get('message', '')}"
                for iss in prior_issues
                if isinstance(iss, dict)
            ]
            data["spec"]["constraints"] = existing + issue_constraints

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
