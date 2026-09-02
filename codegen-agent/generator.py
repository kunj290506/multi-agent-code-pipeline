"""
Code-Gen Agent -- Core Generation Logic.

Generates a single code artifact from a structured specification using
the local Ollama model. Supports both online (live LLM) and offline
(deterministic) modes.
"""

import json
import re
import textwrap

import requests

import config
from spec_schema import ArtifactSpec, GeneratedArtifact


# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an expert code generator. Given a specification for a code artifact,
generate production-quality source code.

Rules:
1. Output ONLY valid JSON -- no markdown fences, no commentary outside the JSON.
2. Use the exact output schema shown below.
3. Generate clean, well-documented code with docstrings and type hints.
4. Follow the conventions of the specified framework.
5. Include necessary imports at the top of the generated code.
6. Do not include test code in the artifact unless explicitly requested.

Output schema:
{
  "artifact_type": "<echoed from spec>",
  "name": "<echoed from spec>",
  "language": "<language>",
  "framework": "<framework>",
  "code": "<the generated source code as a single string>",
  "filename": "<suggested filename>",
  "dependencies": ["<list of required packages>"],
  "explanation": "<brief explanation of the generated code>",
  "warnings": ["<any caveats or warnings>"]
}"""


def _build_prompt(spec: ArtifactSpec) -> str:
    """Build the full prompt for the Ollama model from a specification."""
    spec_block = (
        f"Artifact type: {spec.artifact_type}\n"
        f"Name: {spec.name}\n"
        f"Description: {spec.description}\n"
        f"Language: {spec.language}\n"
        f"Framework: {spec.framework}\n"
    )
    if spec.dependencies:
        spec_block += f"Dependencies: {', '.join(spec.dependencies)}\n"
    if spec.constraints:
        spec_block += f"Constraints:\n"
        for c in spec.constraints:
            spec_block += f"  - {c}\n"
    if spec.context:
        spec_block += f"Context:\n{spec.context}\n"

    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"Specification:\n{spec_block}\n"
        f"Generate the code artifact as JSON:"
    )


def _extract_json(text: str) -> dict:
    """Extract a JSON object from model output, tolerating markdown fences."""
    # Strip markdown code fences if present.
    cleaned = re.sub(r"```(?:json)?\s*", "", text)
    cleaned = cleaned.strip()

    brace_start = cleaned.find("{")
    if brace_start == -1:
        raise ValueError("No JSON object found in model output.")

    depth = 0
    for i in range(brace_start, len(cleaned)):
        if cleaned[i] == "{":
            depth += 1
        elif cleaned[i] == "}":
            depth -= 1
            if depth == 0:
                json_str = cleaned[brace_start : i + 1]
                return json.loads(json_str)

    raise ValueError("Unbalanced braces in model output.")


def _validate_response(response: dict) -> list[str]:
    """Validate the structure of the LLM response."""
    errors = []
    required_fields = ["code", "name", "artifact_type"]
    for field in required_fields:
        if field not in response or not str(response[field]).strip():
            errors.append(f"Missing or empty '{field}' field.")
    return errors


# ---------------------------------------------------------------------------
# Online generation (via Ollama)
# ---------------------------------------------------------------------------

def generate_artifact(spec: ArtifactSpec, max_retries: int = 2) -> GeneratedArtifact:
    """Generate a code artifact using the Ollama LLM.

    Args:
        spec: The artifact specification.
        max_retries: Number of additional LLM attempts if output is invalid.

    Returns:
        A GeneratedArtifact with the generated code and metadata.

    Raises:
        ValueError: If the model fails to produce valid output.
        requests.RequestException: If the Ollama server is unreachable.
    """
    prompt = _build_prompt(spec)
    last_error = ""

    for attempt in range(1 + max_retries):
        if attempt > 0:
            prompt_with_correction = (
                f"{prompt}\n\n"
                f"Your previous response had errors: {last_error}\n"
                f"Please fix the errors and respond with valid JSON only."
            )
        else:
            prompt_with_correction = prompt

        payload = {
            "model": config.OLLAMA_MODEL,
            "prompt": prompt_with_correction,
            "stream": False,
            "options": {
                "temperature": config.TEMPERATURE,
                "num_predict": config.MAX_TOKENS,
            },
        }

        resp = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/generate",
            json=payload,
            timeout=180,
        )
        resp.raise_for_status()
        raw_output = resp.json().get("response", "")

        try:
            result = _extract_json(raw_output)
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = f"JSON parsing failed: {exc}"
            continue

        struct_errors = _validate_response(result)
        if struct_errors:
            last_error = "; ".join(struct_errors)
            continue

        # Fill in defaults from the spec for fields the model may have omitted.
        result.setdefault("artifact_type", spec.artifact_type)
        result.setdefault("name", spec.name)
        result.setdefault("language", spec.language)
        result.setdefault("framework", spec.framework)
        result.setdefault("filename", _suggest_filename(spec))
        result.setdefault("dependencies", spec.dependencies)
        result.setdefault("explanation", "")
        result.setdefault("warnings", [])

        return GeneratedArtifact(**result)

    raise ValueError(
        f"Failed to generate artifact after {1 + max_retries} attempts. "
        f"Last error: {last_error}"
    )


# ---------------------------------------------------------------------------
# Offline generation (deterministic, no LLM)
# ---------------------------------------------------------------------------

_OFFLINE_TEMPLATES = {
    ("rest_endpoint", "python", "fastapi"): textwrap.dedent('''\
        """
        {name} -- Auto-generated REST endpoint.

        {description}
        """

        from fastapi import APIRouter, HTTPException
        from pydantic import BaseModel

        router = APIRouter()


        class {name}Request(BaseModel):
            """Request body for {name}."""
            pass


        class {name}Response(BaseModel):
            """Response body for {name}."""
            message: str


        @router.get("/{route_path}")
        def get_{snake_name}():
            """{description}"""
            return {name}Response(message="{name} endpoint is operational.")


        @router.post("/{route_path}")
        def create_{snake_name}(body: {name}Request):
            """{description}"""
            return {name}Response(message="{name} created successfully.")
    '''),

    ("react_component", "javascript", "react"): textwrap.dedent('''\
        import React, {{ useState }} from "react";

        /**
         * {name} Component
         *
         * {description}
         */
        function {name}({{ title = "{name}" }}) {{
            const [data, setData] = useState(null);

            const handleAction = () => {{
                setData({{ message: "{name} action triggered." }});
            }};

            return (
                <div className="{snake_name}-container">
                    <h2>{{title}}</h2>
                    <button onClick={{handleAction}}>Trigger</button>
                    {{data && <pre>{{JSON.stringify(data, null, 2)}}</pre>}}
                </div>
            );
        }}

        export default {name};
    '''),

    ("utility_module", "python", "none"): textwrap.dedent('''\
        """
        {name} -- Auto-generated utility module.

        {description}
        """


        def {snake_name}_process(data):
            """Process data according to {name} logic.

            Args:
                data: The input data to process.

            Returns:
                The processed result.
            """
            if data is None:
                raise ValueError("Input data must not be None.")
            return {{"status": "processed", "input": data, "module": "{name}"}}
    '''),

    ("database_migration", "python", "sqlite"): textwrap.dedent('''\
        """
        {name} -- Auto-generated database migration.

        {description}
        """

        import sqlite3


        def upgrade(conn: sqlite3.Connection) -> None:
            """Apply the migration."""
            conn.executescript("""
                -- Migration: {name}
                -- {description}
                CREATE TABLE IF NOT EXISTS {snake_name} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)


        def downgrade(conn: sqlite3.Connection) -> None:
            """Revert the migration."""
            conn.execute("DROP TABLE IF EXISTS {snake_name}")
    '''),
}


def _to_snake_case(name: str) -> str:
    """Convert a PascalCase or camelCase name to snake_case."""
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def _suggest_filename(spec: ArtifactSpec) -> str:
    """Suggest a filename based on the artifact spec."""
    snake = _to_snake_case(spec.name)
    ext_map = {
        "python": ".py",
        "javascript": ".jsx",
        "typescript": ".tsx",
    }
    ext = ext_map.get(spec.language, ".py")
    return f"{snake}{ext}"


def generate_artifact_offline(spec: ArtifactSpec) -> GeneratedArtifact:
    """Generate a code artifact deterministically without calling the LLM.

    Uses template-based generation keyed on (artifact_type, language, framework).
    Falls back to a generic template if no exact match is found.

    Args:
        spec: The artifact specification.

    Returns:
        A GeneratedArtifact with template-generated code.
    """
    snake_name = _to_snake_case(spec.name)
    route_path = snake_name.replace("_", "-")

    # Find a matching template.
    key = (spec.artifact_type, spec.language, spec.framework)
    template = _OFFLINE_TEMPLATES.get(key)

    if template is None:
        # Try matching just the artifact type with default language.
        for tpl_key, tpl in _OFFLINE_TEMPLATES.items():
            if tpl_key[0] == spec.artifact_type:
                template = tpl
                break

    if template is None:
        # Fallback generic template.
        template = textwrap.dedent('''\
            """
            {name} -- Auto-generated artifact.

            Type: {artifact_type}
            {description}
            """

            # TODO: Implement {name} logic here.

            def main():
                """Entry point for {name}."""
                return {{"status": "not_implemented", "artifact": "{name}"}}
        ''')

    code = template.format(
        name=spec.name,
        snake_name=snake_name,
        route_path=route_path,
        description=spec.description,
        artifact_type=spec.artifact_type,
    )

    return GeneratedArtifact(
        artifact_type=spec.artifact_type,
        name=spec.name,
        language=spec.language,
        framework=spec.framework,
        code=code,
        filename=_suggest_filename(spec),
        dependencies=spec.dependencies,
        explanation=f"Offline-generated {spec.artifact_type} artifact for '{spec.name}'.",
        warnings=["Generated in offline mode using templates, not LLM."],
    )
