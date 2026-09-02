"""
Planner Agent -- Task Decomposition Module.

Accepts a plain-language feature request and uses the local Ollama model to
decompose it into an ordered list of subtasks. Each subtask is tagged with the
responsible agent and includes a clear description.

The output conforms to a strict JSON schema so downstream consumers can
parse it deterministically.
"""

import json
import re

import requests

import config


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
    },
}


# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a software project planner. Your job is to decompose a feature request
into an ordered list of subtasks. Each subtask must be assigned to exactly one of
the following agents:

- rag-agent: Retrieves relevant documentation and codebase context.
- codegen-agent: Generates source code (API endpoints, UI components, etc.).
- reviewer-agent: Reviews generated code for correctness, style, and security.
- db-agent: Generates database queries and migration logic.
- system: Handles system-level operations like project cleanup/deletion.

Rules:
1. Output ONLY valid JSON -- no markdown fences, no commentary.
2. Use the exact schema shown below.
3. Each subtask must have a unique task_id (e.g. "task_1", "task_2", ...).
4. Specify dependencies as a list of task_ids that must complete first.
5. If the request implies a full project rebuild or replacement (e.g., "delete this whole project"), the FIRST subtask MUST be a cleanup step assigned to the "system" agent.
6. Order subtasks logically: cleanup first (if applicable), then gather context, then generate code,
   then review, then handle database changes as needed.
6. Keep descriptions concise but actionable.

Output schema:
{
  "feature_request": "<original request>",
  "subtasks": [
    {
      "task_id": "task_1",
      "agent": "<agent-name>",
      "description": "<what this subtask does>",
      "dependencies": []
    }
  ]
}"""


def _build_prompt(feature_request: str) -> str:
    """Construct the full prompt for the Ollama model."""
    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"Feature request: {feature_request}\n\n"
        f"Respond with the JSON plan:"
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


def decompose(feature_request: str, max_retries: int = 2) -> dict:
    """Decompose a feature request into a structured task plan.

    Calls the Ollama model to generate the plan, validates it, and retries
    up to *max_retries* times if the output is invalid.

    Args:
        feature_request: Plain-language description of the feature.
        max_retries: Number of additional attempts if the model output is
                     invalid JSON or fails schema validation.

    Returns:
        A validated plan dict conforming to PLAN_SCHEMA.

    Raises:
        ValueError: If the model fails to produce valid output after all retries.
    """
    prompt = _build_prompt(feature_request)

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

        print(f"[INFO] Attempt {attempt + 1}: requesting plan from Ollama...")
        response = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/generate",
            json=payload,
            timeout=300,
        )
        response.raise_for_status()
        raw_output = response.json().get("response", "")
        print(f"[INFO] Received {len(raw_output)} chars from Ollama.")

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


def decompose_offline(feature_request: str) -> dict:
    """Return a deterministic plan without calling the LLM.

    Useful for testing the validation and downstream processing logic
    when the Ollama server is not available.
    """
    feature_request_lower = feature_request.lower()
    
    if "delete" in feature_request_lower and "calculator" in feature_request_lower:
        return {
            "feature_request": feature_request,
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
                    "description": "Generate index.html for a simple calculator app.",
                    "dependencies": ["task_1"],
                },
                {
                    "task_id": "task_3",
                    "agent": "codegen-agent",
                    "description": "Generate styles.css for a simple calculator app.",
                    "dependencies": ["task_1"],
                },
                {
                    "task_id": "task_4",
                    "agent": "codegen-agent",
                    "description": "Generate script.js for a simple calculator app.",
                    "dependencies": ["task_1"],
                },
                {
                    "task_id": "task_5",
                    "agent": "reviewer-agent",
                    "description": "Review the generated calculator app code for correctness and design.",
                    "dependencies": ["task_2", "task_3", "task_4"],
                },
            ]
        }
        
    if "perfcat" in feature_request_lower:
        return {
            "feature_request": feature_request,
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
                },
                {
                    "task_id": "task_3",
                    "agent": "codegen-agent",
                    "description": "Generate styles.css for perfcat webapp.",
                    "dependencies": ["task_1"],
                },
                {
                    "task_id": "task_4",
                    "agent": "codegen-agent",
                    "description": "Generate script.js for perfcat webapp.",
                    "dependencies": ["task_1"],
                },
                {
                    "task_id": "task_5",
                    "agent": "reviewer-agent",
                    "description": "Review the generated perfcat app code.",
                    "dependencies": ["task_2", "task_3", "task_4"],
                },
            ]
        }

    return {
        "feature_request": feature_request,
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
                "agent": "db-agent",
                "description": (
                    "Generate any required database schema changes or "
                    "queries based on the retrieved context."
                ),
                "dependencies": ["task_1"],
            },
            {
                "task_id": "task_3",
                "agent": "codegen-agent",
                "description": (
                    "Generate the implementation code (API endpoints, "
                    "UI components) based on the documentation context "
                    "and database schema."
                ),
                "dependencies": ["task_1", "task_2"],
            },
            {
                "task_id": "task_4",
                "agent": "reviewer-agent",
                "description": (
                    "Review the generated code for correctness, security, "
                    "and adherence to project standards."
                ),
                "dependencies": ["task_3"],
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
