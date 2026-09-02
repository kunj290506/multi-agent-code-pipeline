"""
Code-Gen Agent -- Input Specification Schema.

Defines the strict input format that describes a requested code artifact,
and the strict output format for generated code plus metadata.
"""

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Input specification
# ---------------------------------------------------------------------------

class ArtifactSpec(BaseModel):
    """Specification describing a single code artifact to generate.

    This is the strict input format accepted by the code-generation engine.
    Each spec describes exactly one artifact (e.g. a REST endpoint, a React
    component, a utility module).
    """

    artifact_type: str = Field(
        ...,
        description=(
            "The kind of artifact to generate. "
            "Supported values: 'rest_endpoint', 'react_component', "
            "'utility_module', 'database_migration'."
        ),
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Name of the artifact (e.g. 'UserProfileEndpoint').",
    )
    description: str = Field(
        ...,
        min_length=1,
        description="Plain-language description of what the artifact should do.",
    )
    language: str = Field(
        default="python",
        description="Target programming language (e.g. 'python', 'javascript').",
    )
    framework: str = Field(
        default="fastapi",
        description=(
            "Target framework (e.g. 'fastapi', 'flask', 'react', 'express')."
        ),
    )
    dependencies: list[str] = Field(
        default_factory=list,
        description="List of external dependencies the artifact may use.",
    )
    constraints: list[str] = Field(
        default_factory=list,
        description=(
            "Additional constraints or requirements "
            "(e.g. 'must include input validation', 'use async handlers')."
        ),
    )
    context: str = Field(
        default="",
        description=(
            "Optional additional context such as existing schema definitions "
            "or related code snippets."
        ),
    )


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

class GeneratedArtifact(BaseModel):
    """Output format for a generated code artifact.

    Returned by the code-generation engine after processing a spec.
    """

    artifact_type: str = Field(
        ..., description="Echoed from the input spec."
    )
    name: str = Field(
        ..., description="Echoed from the input spec."
    )
    language: str = Field(
        ..., description="Language of the generated code."
    )
    framework: str = Field(
        ..., description="Framework used in the generated code."
    )
    code: str = Field(
        ..., description="The generated source code."
    )
    filename: str = Field(
        ..., description="Suggested filename for the artifact."
    )
    dependencies: list[str] = Field(
        default_factory=list,
        description="Dependencies required by the generated code.",
    )
    explanation: str = Field(
        default="",
        description="Brief explanation of the generated code.",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Any warnings or caveats about the generated code.",
    )
