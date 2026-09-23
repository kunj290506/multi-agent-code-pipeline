"""
Reviewer / QA Agent -- FastAPI HTTP Wrapper.

Exposes code-review functionality over HTTP for the n8n workflow
and inter-agent communication.

Endpoints:
    POST /review   -- Review code against the rule set.
    GET  /health   -- Liveness / readiness probe.
    GET  /rules    -- Return the available rule set.
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, model_validator

import config
import reviewer
import rules as rules_module

app = FastAPI(
    title="Reviewer / QA Agent API",
    description=(
        "Reviews generated code against a defined rule set covering "
        "syntax, required elements, security, and style."
    ),
    version="1.0.0",
)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class ReviewRequest(BaseModel):
    """Request body for the /review endpoint."""
    code: str | None = Field(
        default=None, description="The source code to review."
    )
    language: str | None = Field(
        default=None,
        description="Programming language of the code.",
    )
    categories: list[str] | None = Field(
        default=None,
        description=(
            "Optional list of rule categories to check. "
            "If omitted, all categories are checked."
        ),
    )
    artifact: dict | None = Field(
        default=None,
        description="Optional CodeGen artifact output wrapper to extract code and language from.",
    )
    project_context: str | None = Field(
        default=None,
        description="Current context of all generated files for cross-file references.",
    )
    feature_request: str | None = Field(
        default=None,
        description="The original user prompt or subtask description to verify logical completeness against.",
    )

    @model_validator(mode="before")
    @classmethod
    def extract_from_artifact(cls, data: dict):
        if not data.get("code") and data.get("artifact") and isinstance(data.get("artifact"), dict):
            artifact = data["artifact"]
            data["code"] = artifact.get("code", "")
            if not data.get("language"):
                data["language"] = artifact.get("language", "python")
        if not data.get("code"):
            raise ValueError("Either 'code' or 'artifact.code' must be provided.")
        if not data.get("language"):
            data["language"] = "python"
        return data


class ReviewIssue(BaseModel):
    """A single issue found during review."""
    rule_id: str
    category: str
    severity: str
    message: str
    line: int | None = None
    suggestion: str = ""


class ReviewResponse(BaseModel):
    """Response body for the /review endpoint."""
    verdict: str
    summary: str
    total_issues: int
    issues_by_severity: dict[str, int]
    issues: list[ReviewIssue]
    categories_checked: list[str]
    reasoning: str | None = Field(
        default=None,
        description=(
            "Optional explanation of the reviewer's reasoning — why issues were "
            "flagged or the code passed. Produced by the LLM; never synthesized."
        ),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health_check():
    """Return service health status."""
    return {"status": "healthy", "service": "reviewer-agent"}


@app.get("/rules")
def get_rules():
    """Return the available rule set."""
    return {"rules": rules_module.RULE_REGISTRY}


@app.post("/review", response_model=ReviewResponse)
def review(request: ReviewRequest):
    """Review the provided code against the rule set."""
    try:
        result = reviewer.review_code(
            code=request.code,
            language=request.language,
            categories=request.categories,
            project_context=request.project_context,
            feature_request=request.feature_request,
        )
        return ReviewResponse(**result)
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
