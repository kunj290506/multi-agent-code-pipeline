"""
Planner Agent -- Task Decomposition Module.

Accepts a plain-language feature request and uses the local Ollama model to
decompose it into an ordered list of subtasks. Each subtask is tagged with the
responsible agent and includes a clear description.

The output conforms to a strict JSON schema so downstream consumers can
parse it deterministically.
"""

import json
import os
import re
import sys

import config

# Add shared module to path so call_llm is importable regardless of how the
# agent is started (directly or from its own directory).
_SHARED = os.path.join(os.path.dirname(__file__), "..", "shared")
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)
from llm import call_llm  # noqa: E402


# ---------------------------------------------------------------------------
# Output schema definition (for documentation and validation)
# ---------------------------------------------------------------------------

SUBTASK_SCHEMA = {
    "type": "object",
    "required": ["task_id", "agent", "description", "dependencies"],
    "properties": {
        "task_id": {
            "type": "string",
            "description": "Unique identifier for the subtask (e.g. 'task_1').",
        },
        "agent": {
            "type": "string",
            "enum": config.VALID_AGENTS,
            "description": "The agent responsible for executing this subtask.",
        },
        "description": {
            "type": "string",
            "description": "Clear, actionable description of what this subtask accomplishes.",
        },
        "dependencies": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of task_id values that must complete before this subtask.",
        },
        "target_filename": {
            "type": "string",
            "description": (
                "For codegen-agent subtasks only: the exact filename to write "
                "(e.g. 'index.html', 'style.css', 'app.py'). Required when the "
                "request is for a whole new project."
            ),
        },
    },
}

PLAN_SCHEMA = {
    "type": "object",
    "required": ["feature_request", "subtasks"],
    "properties": {
        "feature_request": {
            "type": "string",
            "description": "The original feature request, echoed back.",
        },
        "subtasks": {
            "type": "array",
            "items": SUBTASK_SCHEMA,
            "description": "Ordered list of subtasks to fulfill the request.",
        },
        "reasoning": {
            "type": "string",
            "description": "Brief explanation of how you decomposed this request.",
        },
    },
}


# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a software project planner. Your job is to decompose a feature request
into an ordered list of subtasks. Each subtask must be assigned to exactly one of
the following agents:

- rag-agent: Retrieves relevant documentation and codebase context.
- codegen-agent: Generates source code (one file per subtask).
- reviewer-agent: Reviews generated code for correctness, style, and security.
- db-agent: Generates database queries and migration logic.
- system: Handles system-level operations like project cleanup/deletion.

Rules:
1. Output ONLY valid JSON -- no markdown fences, no commentary.
2. Use the exact schema shown below.
3. Each subtask must have a unique task_id (e.g. "task_1", "task_2", ...).
4. Specify dependencies as a list of task_ids that must complete first.
5. If the request implies a full project rebuild or replacement (e.g., "delete this whole project"),
   the FIRST subtask MUST be a cleanup step assigned to the "system" agent.
6. WHOLE-PROJECT REQUESTS (e.g. "build a calculator app", "create a todo app"):
    - Create ONE codegen-agent subtask per required runtime output file (e.g. index.html, style.css, app.js).
   - Each codegen subtask MUST include a "target_filename" field with the exact filename to write.
   - Do NOT create a single codegen subtask for the whole project — one subtask per file only.
    - Do not add README.md or other documentation files unless the request explicitly asks for them.
   - Omit rag-agent unless existing codebase files are available to index.
   - Omit db-agent unless the app genuinely needs a database.
7. SINGLE-FEATURE REQUESTS (adding to an existing project): use rag-agent first if helpful,
   then codegen-agent (one subtask per file changed), then db-agent only if needed.
8. Always include a "reasoning" field in the top-level response explaining your decomposition.
9. Keep descriptions concise but actionable.

Output schema:
{
  "feature_request": "<original request>",
  "reasoning": "<brief explanation of how you decomposed this request>",
  "subtasks": [
    {
      "task_id": "task_1",
      "agent": "<agent-name>",
      "description": "<what this subtask does>",
      "dependencies": [],
      "target_filename": "<filename — required for codegen-agent subtasks in whole-project requests>"
    }
  ]
}"""


def _build_prompt(feature_request: str, file_manifest=None, structural_map=None, rag_context=None) -> str:
    """Construct the full prompt for the Ollama model."""
    prompt = f"{SYSTEM_PROMPT}\n\nFeature request: {feature_request}\n\n"
    
    if file_manifest:
        prompt += f"Project File Manifest:\n{file_manifest}\n\n"
    if structural_map:
        prompt += f"Project Structural Map:\n{structural_map}\n\n"
    if rag_context:
        prompt += f"RAG Context (Project Documentation & Chunks):\n{rag_context}\n\n"
        
    prompt += "Respond with the JSON plan:"
    return prompt


def _is_whole_project_request(feature_request: str) -> bool:
    """Identify requests that benefit from the faster whole-project planner model."""
    request = feature_request.lower()
    return any(
        marker in request
        for marker in ("web app", "web application", "whole project", "full project")
    )


def _extract_json(text: str) -> dict:
    """Extract a JSON object from model output, tolerating markdown fences."""
    # Strip markdown code fences if present.
    cleaned = re.sub(r"```(?:json)?\s*", "", text)
    cleaned = cleaned.strip()

    # Try to find the first JSON object in the text.
    brace_start = cleaned.find("{")
    if brace_start == -1:
        raise ValueError("No JSON object found in model output.")

    # Find the matching closing brace.
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


def _validate_plan(plan: dict) -> list[str]:
    """Validate the plan against the expected schema.

    Returns a list of validation errors (empty if valid).
    """
    errors: list[str] = []

    if "feature_request" not in plan:
        errors.append("Missing 'feature_request' field.")

    subtasks = plan.get("subtasks")
    if not isinstance(subtasks, list):
        errors.append("'subtasks' must be a list.")
        return errors

    if len(subtasks) == 0:
        errors.append("'subtasks' list is empty.")

    seen_ids: set[str] = set()
    for idx, task in enumerate(subtasks):
        prefix = f"subtasks[{idx}]"

        task_id = task.get("task_id")
        if not task_id:
            errors.append(f"{prefix}: missing 'task_id'.")
        elif task_id in seen_ids:
            errors.append(f"{prefix}: duplicate task_id '{task_id}'.")
        else:
            seen_ids.add(task_id)

        agent = task.get("agent")
        if agent not in config.VALID_AGENTS:
            errors.append(
                f"{prefix}: invalid agent '{agent}'. "
                f"Must be one of {config.VALID_AGENTS}."
            )

        if not task.get("description"):
            errors.append(f"{prefix}: missing 'description'.")

        deps = task.get("dependencies")
        if not isinstance(deps, list):
            errors.append(f"{prefix}: 'dependencies' must be a list.")
        else:
            for dep in deps:
                if dep not in seen_ids:
                    errors.append(
                        f"{prefix}: dependency '{dep}' references an unknown "
                        f"or later task_id."
                    )

    return errors


def decompose(feature_request: str, max_retries: int = 2, file_manifest=None, structural_map=None, rag_context=None) -> dict:
    """Decompose a feature request into a structured task plan.

    Calls the Ollama model to generate the plan, validates it, and retries
    up to *max_retries* times if the output is invalid.

    Args:
        feature_request: Plain-language description of the feature.
        max_retries: Number of additional attempts if the model output is
                     invalid JSON or fails schema validation.
        file_manifest: Existing files manifest.
        structural_map: Existing code structure map.
        rag_context: RAG answers.

    Returns:
        A validated plan dict conforming to PLAN_SCHEMA.

    Raises:
        ValueError: If the model fails to produce valid output after all retries.
    """
    prompt = _build_prompt(feature_request, file_manifest, structural_map, rag_context)

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

        provider = os.getenv("LLM_PROVIDER", "ollama")
        print(f"[INFO] Attempt {attempt + 1}: requesting plan via {provider}...")
        planner_model = config.GROQ_MODEL
        if _is_whole_project_request(feature_request):
            planner_model = config.GROQ_WHOLE_PROJECT_MODEL
        llm_result = call_llm(
            prompt_with_correction,
            model=planner_model if os.getenv("LLM_PROVIDER", "ollama").lower() == "groq" else None,
            temperature=config.TEMPERATURE,
            max_tokens=config.MAX_TOKENS,
            context_size=config.OLLAMA_CONTEXT_SIZE,
            timeout=300,
        )
        raw_output = llm_result.text
        if llm_result.schema_errors:
            print(f"[WARN] LLM backend issues: {llm_result.schema_errors}")
        print(f"[INFO] Received {len(raw_output)} chars from {llm_result.provider} in {llm_result.duration_ms}ms.")

        try:
            plan = _extract_json(raw_output)
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = f"JSON parsing failed: {exc}"
            print(f"[WARN] {last_error}")
            continue

        validation_errors = _validate_plan(plan)
        if validation_errors:
            last_error = "; ".join(validation_errors)
            print(f"[WARN] Validation errors: {last_error}")
            continue

        return plan

    raise ValueError(
        f"Failed to generate a valid plan after {1 + max_retries} attempts. "
        f"Last error: {last_error}"
    )


def decompose_offline(feature_request: str, file_manifest=None, structural_map=None, rag_context=None) -> dict:
    """Return a deterministic plan without calling the LLM.

    Useful for testing the validation and downstream processing logic
    when the Ollama server is not available.
    """
    feature_request_lower = feature_request.lower()
    
    if "delete" in feature_request_lower and "calculator" in feature_request_lower:
        return {
            "feature_request": feature_request,
            "reasoning": (
                "Whole-project request: calculator app. Cleaning existing workspace first, "
                "then generating one file per output artifact (HTML structure, CSS styles, "
                "JS logic), each as a separate codegen subtask with explicit target_filename."
            ),
            "subtasks": [
                {
                    "task_id": "task_1",
                    "agent": "system",
                    "description": "Delete the entire existing project directory to prepare for a fresh build.",
                    "dependencies": [],
                },
                {
                    "task_id": "task_2",
                    "agent": "codegen-agent",
                    "description": "Generate index.html for a simple calculator app with buttons for 0-9, +, -, *, /, =, C and a display.",
                    "dependencies": ["task_1"],
                    "target_filename": "index.html",
                },
                {
                    "task_id": "task_3",
                    "agent": "codegen-agent",
                    "description": "Generate style.css for the calculator app — dark theme, grid layout for buttons.",
                    "dependencies": ["task_1"],
                    "target_filename": "style.css",
                },
                {
                    "task_id": "task_4",
                    "agent": "codegen-agent",
                    "description": "Generate script.js for the calculator app — handles button clicks, evaluates expressions, updates display.",
                    "dependencies": ["task_1"],
                    "target_filename": "script.js",
                },
            ]
        }

    if "perfcat" in feature_request_lower:
        return {
            "feature_request": feature_request,
            "reasoning": (
                "Whole-project request: perfcat webapp. Generating one file per output artifact "
                "with explicit target_filename per codegen subtask."
            ),
            "subtasks": [
                {
                    "task_id": "task_1",
                    "agent": "system",
                    "description": "Delete the entire existing project directory to prepare for a fresh build.",
                    "dependencies": [],
                },
                {
                    "task_id": "task_2",
                    "agent": "codegen-agent",
                    "description": "Generate index.html for perfcat webapp.",
                    "dependencies": ["task_1"],
                    "target_filename": "index.html",
                },
                {
                    "task_id": "task_3",
                    "agent": "codegen-agent",
                    "description": "Generate style.css for perfcat webapp.",
                    "dependencies": ["task_1"],
                    "target_filename": "style.css",
                },
                {
                    "task_id": "task_4",
                    "agent": "codegen-agent",
                    "description": "Generate script.js for perfcat webapp.",
                    "dependencies": ["task_1"],
                    "target_filename": "script.js",
                },
            ]
        }

    # Detect whole-project requests by keyword heuristic.
    # Handles a wide range of natural phrasings: "build a X", "create a X",
    # "I want a X app", "write me a X", "give me a X app", etc.
    # The goal is to catch any phrasing where the user is asking for a complete
    # new standalone application rather than a feature on an existing project.
    whole_project_keywords = [
        "build a ", "build an ",
        "create a ", "create an ",
        "make a ", "make an ",
        "scaffold a ", "scaffold an ",
        # "generate a" omitted — too broad: also matches "Generate a REST endpoint"
        "write a ", "write an ",
        "i want a ", "i want an ",
        "give me a ", "give me an ",
        "write me a ", "write me an ",
        "develop a ", "develop an ",
        "design a ", "design an ",
    ]
    # Also treat any request ending in "app", "application", "website", "webapp",
    # "web app", "tool", "game" as a whole-project request if no feature verb is present.
    whole_project_suffixes = ["app", "application", "website", "web app", "webapp", "tool", "game", "calculator", "dashboard"]
    ends_with_project_noun = any(feature_request_lower.rstrip(".! ").endswith(suf) for suf in whole_project_suffixes)
    is_whole_project = (
        any(kw in feature_request_lower for kw in whole_project_keywords)
        or ends_with_project_noun
    )

    if is_whole_project:
        app_name = feature_request.strip().rstrip(".").rstrip("!")
        reasoning = (
            f"Whole-project request detected: '{app_name}'. Scaffolding as separate "
            "per-file codegen subtasks with target_filename."
        )
        if file_manifest or structural_map or rag_context:
            reasoning += " (Context injected via file_manifest/structural_map/rag_context)"
            
        return {
            "feature_request": feature_request,
            "reasoning": reasoning,
            "subtasks": [
                {
                    "task_id": "task_1",
                    "agent": "codegen-agent",
                    "description": f"Generate index.html — the main HTML structure for: {app_name}",
                    "dependencies": [],
                    "target_filename": "index.html",
                },
                {
                    "task_id": "task_2",
                    "agent": "codegen-agent",
                    "description": f"Generate style.css — styling for: {app_name}",
                    "dependencies": [],
                    "target_filename": "style.css",
                },
                {
                    "task_id": "task_3",
                    "agent": "codegen-agent",
                    "description": f"Generate script.js — all interactivity and logic for: {app_name}",
                    "dependencies": [],
                    "target_filename": "script.js",
                },
                {
                    "task_id": "task_4",
                    "agent": "codegen-agent",
                    "description": f"Generate README.md — project description and usage instructions for: {app_name}",
                    "dependencies": [],
                    "target_filename": "README.md",
                },
            ],
        }

    return {
        "feature_request": feature_request,
        "reasoning": (
            "Single-feature request: using standard rag → codegen → review pipeline "
            "to add to the existing project."
        ),
        "subtasks": [
            {
                "task_id": "task_1",
                "agent": "rag-agent",
                "description": (
                    f"Retrieve relevant documentation and existing code "
                    f"related to: {feature_request}"
                ),
                "dependencies": [],
            },
            {
                "task_id": "task_2",
                "agent": "codegen-agent",
                "description": (
                    "Generate the implementation code (API endpoints, "
                    "UI components) based on the documentation context."
                ),
                "dependencies": ["task_1"],
            },
            {
                "task_id": "task_3",
                "agent": "reviewer-agent",
                "description": (
                    "Review the generated code for correctness, security, "
                    "and adherence to project standards."
                ),
                "dependencies": ["task_2"],
            },
        ],
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Decompose a feature request into agent subtasks."
    )
    parser.add_argument("request", help="Plain-language feature request.")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Use offline mode (no Ollama required).",
    )
    args = parser.parse_args()

    if args.offline:
        result = decompose_offline(args.request)
    else:
        result = decompose(args.request)

    print(json.dumps(result, indent=2))
