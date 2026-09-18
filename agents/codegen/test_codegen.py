"""
Test script for the Code-Gen Agent.

Covers both offline (deterministic) and online (live model) modes
with multiple example specifications.
"""

import json
import os
import sys

# Ensure the codegen-agent directory is on the Python path.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI
from fastapi.testclient import TestClient

import generator
from spec_schema import ArtifactSpec, GeneratedArtifact


# ---------------------------------------------------------------------------
# Example specifications
# ---------------------------------------------------------------------------

EXAMPLE_SPECS = [
    ArtifactSpec(
        artifact_type="rest_endpoint",
        name="UserProfile",
        description="An endpoint that returns user profile details by user ID.",
        language="python",
        framework="fastapi",
        dependencies=["fastapi", "pydantic"],
        constraints=["must include input validation", "return 404 if user not found"],
    ),
    ArtifactSpec(
        artifact_type="react_component",
        name="TaskCard",
        description="A card component displaying task title, status, and priority.",
        language="javascript",
        framework="react",
        dependencies=["react"],
        constraints=["use functional component with hooks"],
    ),
    ArtifactSpec(
        artifact_type="utility_module",
        name="DateFormatter",
        description="A utility that formats dates into human-readable strings.",
        language="python",
        framework="none",
        dependencies=[],
        constraints=["handle timezone-aware datetimes"],
    ),
    ArtifactSpec(
        artifact_type="database_migration",
        name="AddTagsTable",
        description="Migration to create a tags table for task categorization.",
        language="python",
        framework="sqlite",
        dependencies=[],
        constraints=["include both upgrade and downgrade functions"],
    ),
    ArtifactSpec(
        artifact_type="rest_endpoint",
        name="HealthCheck",
        description="A simple health check endpoint that returns service status.",
        language="python",
        framework="fastapi",
        dependencies=["fastapi"],
        constraints=[],
    ),
]


def run_tests():
    """Run all code-gen agent tests and report results."""
    passed = 0
    failed = 0

    def check(name, condition, detail=""):
        nonlocal passed, failed
        status = "PASS" if condition else "FAIL"
        if condition:
            passed += 1
        else:
            failed += 1
        print(f"  [{status}] {name}" + (f" -- {detail}" if detail else ""))

    print("=" * 70)
    print("CODE-GEN AGENT -- TEST SUITE")
    print("=" * 70)

    # ------------------------------------------------------------------
    # Offline generation tests
    # ------------------------------------------------------------------
    print("\n--- Offline Generation ---")
    for i, spec in enumerate(EXAMPLE_SPECS, 1):
        try:
            artifact = generator.generate_artifact_offline(spec)
            check(
                f"Offline spec {i} ({spec.name}): generates successfully",
                True,
            )
            check(
                f"Offline spec {i} ({spec.name}): code is non-empty",
                len(artifact.code.strip()) > 0,
            )
            check(
                f"Offline spec {i} ({spec.name}): name matches",
                artifact.name == spec.name,
            )
            check(
                f"Offline spec {i} ({spec.name}): artifact_type matches",
                artifact.artifact_type == spec.artifact_type,
            )
            check(
                f"Offline spec {i} ({spec.name}): filename is set",
                len(artifact.filename) > 0,
                f"filename='{artifact.filename}'",
            )
            check(
                f"Offline spec {i} ({spec.name}): has offline warning",
                any("offline" in w.lower() for w in artifact.warnings),
            )
        except Exception as exc:
            check(
                f"Offline spec {i} ({spec.name}): generates successfully",
                False,
                str(exc),
            )

    # ------------------------------------------------------------------
    # JSON output format validation
    # ------------------------------------------------------------------
    print("\n--- Output Format Validation ---")
    for i, spec in enumerate(EXAMPLE_SPECS, 1):
        artifact = generator.generate_artifact_offline(spec)
        artifact_dict = artifact.model_dump()

        # Verify all required fields are present.
        required_fields = [
            "artifact_type", "name", "language", "framework",
            "code", "filename", "dependencies", "explanation", "warnings",
        ]
        all_present = all(f in artifact_dict for f in required_fields)
        check(
            f"Output spec {i} ({spec.name}): all required fields present",
            all_present,
        )

        # Verify JSON serialization round-trip.
        json_str = json.dumps(artifact_dict)
        round_trip = json.loads(json_str)
        check(
            f"Output spec {i} ({spec.name}): JSON round-trip succeeds",
            round_trip == artifact_dict,
        )

    # ------------------------------------------------------------------
    # Helper function tests
    # ------------------------------------------------------------------
    print("\n--- Helper Functions ---")

    # Snake case conversion.
    test_cases = [
        ("UserProfile", "user_profile"),
        ("TaskCard", "task_card"),
        ("DateFormatter", "date_formatter"),
        ("AddTagsTable", "add_tags_table"),
        ("HealthCheck", "health_check"),
        ("simpleword", "simpleword"),
        ("HTTPServer", "http_server"),
    ]
    for pascal, expected in test_cases:
        result = generator._to_snake_case(pascal)
        check(
            f"Snake case: '{pascal}' -> '{expected}'",
            result == expected,
            f"got '{result}'",
        )

    # Filename suggestion.
    spec = ArtifactSpec(
        artifact_type="rest_endpoint",
        name="UserProfile",
        description="Test",
        language="python",
        framework="fastapi",
    )
    fn = generator._suggest_filename(spec)
    check("Filename suggestion for Python", fn == "user_profile.py", f"got '{fn}'")

    spec_js = ArtifactSpec(
        artifact_type="react_component",
        name="TaskCard",
        description="Test",
        language="javascript",
        framework="react",
    )
    fn_js = generator._suggest_filename(spec_js)
    check("Filename suggestion for JS", fn_js == "task_card.jsx", f"got '{fn_js}'")

    # ------------------------------------------------------------------
    # JSON extraction tests
    # ------------------------------------------------------------------
    print("\n--- JSON Extraction ---")

    # Clean JSON.
    raw = '{"code": "print(1)", "name": "Test"}'
    result = generator._extract_json(raw)
    check("Extract clean JSON", result["name"] == "Test")

    # JSON with markdown fences.
    raw_fenced = '```json\n{"code": "x = 1", "name": "Fenced"}\n```'
    result = generator._extract_json(raw_fenced)
    check("Extract JSON from markdown fences", result["name"] == "Fenced")

    # JSON with surrounding text.
    raw_surrounded = 'Here is the output:\n{"code": "y = 2", "name": "Surrounded"}\nDone.'
    result = generator._extract_json(raw_surrounded)
    check("Extract JSON from surrounding text", result["name"] == "Surrounded")

    # Invalid JSON.
    try:
        generator._extract_json("no json here")
        check("Reject input without JSON", False, "should have raised")
    except ValueError:
        check("Reject input without JSON", True)

    # ------------------------------------------------------------------
    # API tests (offline mode only)
    # ------------------------------------------------------------------
    print("\n--- API Endpoint Tests ---")

    import api
    client = TestClient(api.app)

    resp = client.get("/health")
    check("GET /health returns 200", resp.status_code == 200)
    check(
        "Health response has correct service name",
        resp.json().get("service") == "codegen-agent",
    )

    resp = client.get("/spec-schema")
    check("GET /spec-schema returns 200", resp.status_code == 200)
    schema_data = resp.json()
    check(
        "Spec schema has input_schema",
        "input_schema" in schema_data,
    )
    check(
        "Spec schema has output_schema",
        "output_schema" in schema_data,
    )

    # Generate via API in offline mode.
    resp = client.post("/generate", json={
        "spec": EXAMPLE_SPECS[0].model_dump(),
        "offline": True,
    })
    check("POST /generate (offline) returns 200", resp.status_code == 200)
    gen_data = resp.json()
    check("Generate response has success=True", gen_data.get("success") is True)
    check("Generate response has mode=offline", gen_data.get("mode") == "offline")
    check(
        "Generate response has artifact with code",
        len(gen_data.get("artifact", {}).get("code", "")) > 0,
    )

    # ------------------------------------------------------------------
    # Online generation test (skipped if Ollama is not running)
    # ------------------------------------------------------------------
    print("\n--- Online Generation (requires Ollama) ---")
    try:
        import requests as req
        health_resp = req.get(f"{generator.config.OLLAMA_BASE_URL}/api/tags", timeout=3)
        if health_resp.status_code == 200:
            try:
                online_spec = ArtifactSpec(
                    artifact_type="rest_endpoint",
                    name="PingEndpoint",
                    description="A simple ping endpoint that returns pong.",
                    language="python",
                    framework="fastapi",
                )
                artifact = generator.generate_artifact(online_spec)
                check(
                    "Online generation succeeds",
                    len(artifact.code.strip()) > 0,
                )
                check(
                    "Online artifact has correct name",
                    artifact.name == "PingEndpoint",
                )
            except Exception as exc:
                check("Online generation succeeds", False, str(exc))
        else:
            print("  [SKIP] Ollama not healthy, skipping online tests.")
    except Exception:
        print("  [SKIP] Ollama not reachable, skipping online tests.")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print(f"RESULTS: {passed} passed, {failed} failed, {passed + failed} total")
    print("=" * 70)

    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
