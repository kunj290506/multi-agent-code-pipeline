"""
Code-Gen Agent -- Core Generation Logic.

Generates a single code artifact from a structured specification using
the local Ollama model. Supports both online (live LLM) and offline
(deterministic) modes.
"""

import json
import os
import re
import sys
import textwrap

import config
from spec_schema import ArtifactSpec, GeneratedArtifact

# Shared LLM dispatch
_SHARED = os.path.join(os.path.dirname(__file__), "..", "shared")
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)
from llm import call_llm  # noqa: E402


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
        spec_block += "Constraints:\n"
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
    """Extract a JSON object from model output, tolerating markdown fences and think blocks.

    Handles three common failure modes from reasoning LLMs:
    1. <think>...</think> preamble before the JSON.
    2. Markdown code fences wrapping the JSON.
    3. Unescaped newlines/quotes inside string fields (unterminated string errors)
       — in this case we extract the 'code' block separately and re-assemble.
    """
    # Strip <think>...</think> blocks produced by reasoning models (e.g. qwen3).
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    # Strip markdown code fences (```json ... ``` or ``` ... ```).
    cleaned = re.sub(r"```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"```", "", cleaned)
    cleaned = cleaned.strip()

    # Try a direct parse first (model output is clean JSON).
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Try raw_decode from the first '{' (handles trailing garbage after valid JSON).
    brace_start = cleaned.find("{")
    if brace_start == -1:
        raise ValueError("No JSON object found in model output.")

    decoder = json.JSONDecoder()
    try:
        obj, _ = decoder.raw_decode(cleaned, brace_start)
        return obj
    except json.JSONDecodeError:
        pass

    # Last resort: the "code" field contains raw newlines/unescaped characters that
    # break the JSON parser.  Extract every field individually using regex and
    # reconstruct a clean dict — this is resilient to unterminated-string errors.
    result: dict = {}

    # Extract simple quoted string fields (single-line values).
    for field in ("artifact_type", "name", "language", "framework", "filename", "explanation"):
        m = re.search(
            rf'"{field}"\s*:\s*"((?:[^"\\]|\\.)*)"',
            cleaned,
        )
        if m:
            result[field] = m.group(1).encode("raw_unicode_escape").decode("unicode_escape", errors="replace")

    # Extract the "code" field: everything between the first "code": " and the
    # closing sequence that ends the JSON string (look for the last field or closing brace).
    # Strategy: grab everything after `"code":` up to the next top-level `"` key or `}`.
    code_match = re.search(r'"code"\s*:\s*"(.*?)(?<!\\)"\s*(?:,\s*"|\s*\})', cleaned, re.DOTALL)
    if code_match:
        raw_code = code_match.group(1)
        # Unescape JSON escape sequences.
        try:
            result["code"] = json.loads(f'"{raw_code}"')
        except Exception:
            result["code"] = raw_code
    else:
        # Broadest fallback: everything after "code": until end of string block.
        code_match2 = re.search(r'"code"\s*:\s*"(.*)', cleaned, re.DOTALL)
        if code_match2:
            raw = code_match2.group(1).rstrip().rstrip('"').rstrip(",").rstrip("}")
            result["code"] = raw

    # Extract list fields (dependencies, warnings).
    for field in ("dependencies", "warnings"):
        m = re.search(rf'"{field}"\s*:\s*(\[.*?\])', cleaned, re.DOTALL)
        if m:
            try:
                result[field] = json.loads(m.group(1))
            except Exception:
                result[field] = []

    if not result:
        raise ValueError(f"Could not parse JSON from model output. Raw snippet: {cleaned[:300]}")

    return result


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

        llm_result = call_llm(
            prompt_with_correction,
            temperature=config.TEMPERATURE,
            max_tokens=config.MAX_TOKENS,
            context_size=config.OLLAMA_CONTEXT_SIZE,
            timeout=600,
        )
        raw_output = llm_result.text
        if llm_result.schema_errors:
            print(f"[WARN] LLM backend issues: {llm_result.schema_errors}")

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
    # ── Web artifact templates ──────────────────────────────────────────────

    ("html_page", "html", "none"): textwrap.dedent('''\
        <!DOCTYPE html>
        <html lang="en">
        <head>
          <meta charset="UTF-8" />
          <meta name="viewport" content="width=device-width, initial-scale=1.0" />
          <title>{name}</title>
          <link rel="stylesheet" href="style.css" />
        </head>
        <body>
          <!-- {description} -->
          <div id="app">
            <h1>{name}</h1>
                        <p id="description">{description}</p>
                        <main id="content" class="content"></main>
          </div>
          <script src="script.js"></script>
        </body>
        </html>
    '''),

    ("stylesheet", "css", "none"): textwrap.dedent('''\
        /* {description} */
        *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

        body {{
          min-height: 100vh;
          display: flex;
          align-items: center;
          justify-content: center;
          background: #1a1a2e;
          font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        }}

        #app {{
          background: #16213e;
          border-radius: 16px;
          padding: 24px;
          box-shadow: 0 8px 32px rgba(0,0,0,0.4);
          width: 320px;
        }}

        h1 {{
          color: #e2e2e2;
          font-size: 14px;
          letter-spacing: 2px;
          text-transform: uppercase;
          margin-bottom: 16px;
          text-align: center;
        }}

        .display {{
          background: #0f3460;
          color: #e2e2e2;
          font-size: 36px;
          text-align: right;
          padding: 16px 20px;
          border-radius: 8px;
          margin-bottom: 16px;
          min-height: 64px;
          word-break: break-all;
          overflow: hidden;
        }}

        .buttons {{
          display: grid;
          grid-template-columns: repeat(4, 1fr);
          gap: 8px;
        }}

        .btn {{
          background: #1a1a2e;
          color: #e2e2e2;
          border: 1px solid #0f3460;
          border-radius: 8px;
          padding: 18px 0;
          font-size: 18px;
          cursor: pointer;
          transition: background 0.15s;
        }}

        .btn:hover {{ background: #0f3460; }}
        .btn:active {{ background: #e94560; color: #fff; }}

        .btn-clear {{ background: #e94560; color: #fff; }}
        .btn-clear:hover {{ background: #c73652; }}

        .btn-equals {{
          background: #e94560;
          color: #fff;
          grid-row: span 2;
        }}
        .btn-equals:hover {{ background: #c73652; }}

        .btn-wide {{ grid-column: span 2; }}
    '''),

    ("script", "javascript", "none"): textwrap.dedent('''\
        // {description}
                // Generated in offline mode. The online LLM path should be used for
                // request-specific application behavior.

        (function () {{
          'use strict';

                    const content = document.getElementById('content');
                    if (content) {{
                        content.textContent = 'Request-specific behavior is generated by the online model.';
                    }}
        }})();
    '''),

    ("documentation", "markdown", "none"): textwrap.dedent('''\
        # {name}

        > {description}

        ## Overview

        This project was generated by the multi-agent code pipeline.

        ## Files

        | File | Purpose |
        |------|---------|
        | `index.html` | Main HTML structure |
        | `style.css` | Styles and layout |
        | `script.js` | Interactive behaviour |

        ## Usage

        Open `index.html` in a browser to run the app locally.
        The pipeline backend can also serve it automatically via `http.server`.

        ## Generated by

        Multi-Agent Code Pipeline (offline mode)
    '''),
}


def _to_snake_case(name: str) -> str:
    """Convert a PascalCase or camelCase name to snake_case."""
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def _suggest_filename(spec: ArtifactSpec) -> str:
    """Suggest a filename based on the artifact type and language.

    For web artifact types the canonical filename is returned directly so that
    the generated file always lands at the right path (index.html, style.css, …)
    regardless of the spec's `name` field.
    """
    if spec.target_filename:
        return spec.target_filename

    # Web / document types: canonical filenames
    canonical = {
        "html_page": "index.html",
        "stylesheet": "style.css",
        "script": "script.js",
        "documentation": "README.md",
    }
    if spec.artifact_type in canonical:
        return canonical[spec.artifact_type]

    snake = _to_snake_case(spec.name)
    ext_map = {
        "python": ".py",
        "javascript": ".jsx",
        "typescript": ".tsx",
        "html": ".html",
        "css": ".css",
        "sql": ".sql",
        "markdown": ".md",
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

    # Build a constraints comment block for offline output so the diff is
    # visible between attempt 1 and retry attempts (prior_issues wired via
    # spec.constraints by the API layer).
    constraints_comment = ""
    if spec.constraints:
        lines = "\n".join(f"  - {c}" for c in spec.constraints)
        constraints_comment = f"<!-- Constraints:\n{lines}\n-->\n" if spec.language in ("html", "css") else f"# Constraints:\n{lines.replace('  -', '#  -')}\n"

    # Find a matching template.
    key = (spec.artifact_type, spec.language, spec.framework)
    template = _OFFLINE_TEMPLATES.get(key)

    if template is None:
        # Try matching just the artifact type.
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

    # Prepend constraints comment if this is a retry (constraints were set).
    if constraints_comment and spec.constraints:
        code = constraints_comment + code

    filename = _suggest_filename(spec)

    return GeneratedArtifact(
        artifact_type=spec.artifact_type,
        name=spec.name,
        language=spec.language,
        framework=spec.framework,
        code=code,
        filename=filename,
        dependencies=spec.dependencies,
        explanation=f"Offline-generated {spec.artifact_type} artifact for '{spec.name}'.",
        warnings=["Generated in offline mode using templates, not LLM."],
    )
