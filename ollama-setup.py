"""
Ollama Local Model Setup and Verification Script.

This script automates the process of:
1. Checking connectivity to the Ollama server.
2. Pulling a specified model (default: mistral).
3. Verifying the model responds correctly to a test prompt.

Usage:
    python ollama-setup.py [--model MODEL_NAME] [--host OLLAMA_HOST]

Requirements:
    - Python 3.10+
    - The 'requests' package (pip install requests)
    - A running Ollama instance (via Docker or local install)
"""

import argparse
import json
import sys
import time

try:
    import requests
except ImportError:
    print(
        "ERROR: The 'requests' package is required. "
        "Install it with: pip install requests"
    )
    sys.exit(1)


DEFAULT_MODEL = "qwen2.5:7b-instruct-q4_K_M"
DEFAULT_HOST = "http://localhost:11434"
PULL_TIMEOUT_SECONDS = 600
GENERATE_TIMEOUT_SECONDS = 120


def check_server(host: str) -> bool:
    """Verify that the Ollama server is reachable."""
    url = f"{host}/api/tags"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        print(f"[OK] Ollama server is reachable at {host}")
        return True
    except requests.ConnectionError:
        print(f"[FAIL] Cannot connect to Ollama server at {host}")
        print("       Make sure the Ollama container is running:")
        print("       docker compose up -d ollama")
        return False
    except requests.HTTPError as exc:
        print(f"[FAIL] Ollama server returned an error: {exc}")
        return False


def list_models(host: str) -> list[str]:
    """Return a list of model names currently available on the server."""
    url = f"{host}/api/tags"
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    data = response.json()
    return [m["name"] for m in data.get("models", [])]


def pull_model(host: str, model: str) -> bool:
    """Pull a model from the Ollama registry. Streams progress to stdout."""
    url = f"{host}/api/pull"
    payload = {"name": model, "stream": True}

    print(f"[...] Pulling model '{model}' -- this may take several minutes...")

    try:
        with requests.post(
            url, json=payload, stream=True, timeout=PULL_TIMEOUT_SECONDS
        ) as response:
            response.raise_for_status()
            last_status = ""
            for line in response.iter_lines():
                if not line:
                    continue
                data = json.loads(line)
                status = data.get("status", "")
                if status != last_status:
                    print(f"      {status}")
                    last_status = status
                if data.get("error"):
                    print(f"[FAIL] Pull error: {data['error']}")
                    return False
    except requests.exceptions.Timeout:
        print(f"[FAIL] Model pull timed out after {PULL_TIMEOUT_SECONDS}s")
        return False
    except requests.HTTPError as exc:
        print(f"[FAIL] Pull request failed: {exc}")
        return False

    print(f"[OK] Model '{model}' pulled successfully.")
    return True


def verify_model(host: str, model: str) -> bool:
    """Send a test prompt to the model and validate the response."""
    url = f"{host}/api/generate"
    test_prompt = (
        "Respond with exactly one sentence: What is the capital of France?"
    )
    payload = {
        "model": model,
        "prompt": test_prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 100,
        },
    }

    print(f"[...] Sending test prompt to '{model}'...")
    start = time.time()

    try:
        response = requests.post(
            url, json=payload, timeout=GENERATE_TIMEOUT_SECONDS
        )
        response.raise_for_status()
    except requests.exceptions.Timeout:
        print(f"[FAIL] Model did not respond within {GENERATE_TIMEOUT_SECONDS}s")
        return False
    except requests.HTTPError as exc:
        print(f"[FAIL] Generation request failed: {exc}")
        return False

    elapsed = time.time() - start
    data = response.json()
    answer = data.get("response", "").strip()

    if not answer:
        print("[FAIL] Model returned an empty response.")
        return False

    print(f"[OK] Model responded in {elapsed:.1f}s")
    print(f"      Prompt:   {test_prompt}")
    print(f"      Response: {answer}")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Set up and verify a local Ollama model."
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Model to pull and test (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"Ollama server URL (default: {DEFAULT_HOST})",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  Ollama Local Model Setup")
    print("=" * 60)
    print()

    # Step 1: Check connectivity
    if not check_server(args.host):
        sys.exit(1)

    # Step 2: Check if model is already available
    available = list_models(args.host)
    print(f"[INFO] Models currently available: {available or '(none)'}")

    model_present = any(
        m == args.model or m.startswith(f"{args.model}:")
        for m in available
    )

    # Step 3: Pull model if not present
    if model_present:
        print(f"[OK] Model '{args.model}' is already available.")
    else:
        if not pull_model(args.host, args.model):
            sys.exit(1)

    # Step 4: Verify with test prompt
    print()
    if not verify_model(args.host, args.model):
        print()
        print("[FAIL] Model verification failed.")
        sys.exit(1)

    print()
    print("=" * 60)
    print("  Setup complete. The local model is ready for use.")
    print("=" * 60)


if __name__ == "__main__":
    main()
