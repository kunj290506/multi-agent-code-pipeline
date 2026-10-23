# backend/n8n_client.py
"""Client for communicating with n8n workflow automation."""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger("backend.n8n")

N8N_BASE_URL = os.environ.get("N8N_BASE_URL", "http://127.0.0.1:5678").rstrip("/")
N8N_WEBHOOK_URL = os.environ.get("N8N_WEBHOOK_URL", f"{N8N_BASE_URL}/webhook").rstrip("/")

ALLOWED_WORKFLOWS = {"run-tests", "summarize-changes", "notify"}


async def check_n8n_health() -> bool:
    """Check if n8n instance is reachable."""
    try:
        async with httpx.AsyncClient(timeout=0.6) as client:
            resp = await client.get(f"{N8N_BASE_URL}/healthz")
            if resp.status_code in (200, 401, 403):
                return True
            # Fallback check root
            resp2 = await client.get(N8N_BASE_URL)
            return resp2.status_code in (200, 401, 403)
    except Exception:
        return False


async def import_workflows_if_needed(n8n_dir: Optional[str] = None) -> List[str]:
    """Import and activate default workflows from n8n folder if n8n API is available."""
    if not await check_n8n_health():
        logger.info("n8n is not reachable; skipping automatic workflow import.")
        return []

    if not n8n_dir:
        n8n_dir = str(Path(__file__).parent.parent / "n8n")

    imported = []
    headers = {"Content-Type": "application/json"}
    n8n_path = Path(n8n_dir)
    if not n8n_path.exists():
        return []

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Query existing workflows
            existing_names = set()
            try:
                resp = await client.get(f"{N8N_BASE_URL}/api/v1/workflows", headers=headers)
                if resp.status_code == 200:
                    data = resp.json().get("data", [])
                    existing_names = {wf.get("name") for wf in data if wf.get("name")}
            except Exception:
                pass

            for wf_file in n8n_path.glob("*.json"):
                try:
                    with open(wf_file, "r", encoding="utf-8") as f:
                        wf_json = json.load(f)
                    wf_name = wf_json.get("name")
                    if wf_name and wf_name not in existing_names:
                        post_resp = await client.post(
                            f"{N8N_BASE_URL}/api/v1/workflows",
                            json=wf_json,
                            headers=headers,
                        )
                        if post_resp.status_code in (200, 201):
                            imported.append(wf_name)
                            logger.info(f"Imported n8n workflow: {wf_name}")
                except Exception as exc:
                    logger.warning(f"Failed to import workflow {wf_file.name}: {exc}")
    except Exception as exc:
        logger.warning(f"Error checking n8n workflows: {exc}")

    return imported


async def trigger_workflow(name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Trigger one of the allowed n8n webhooks.
    Allowed: 'run-tests', 'summarize-changes', 'notify'.
    """
    if name not in ALLOWED_WORKFLOWS:
        return {
            "success": False,
            "error": f"Workflow '{name}' is not in the allowed list: {', '.join(sorted(ALLOWED_WORKFLOWS))}",
        }

    is_online = await check_n8n_health()
    if not is_online:
        return {
            "success": False,
            "error": f"n8n server is offline at {N8N_BASE_URL}. Start n8n/Docker to run automation workflows.",
            "workflow": name,
        }

    url = f"{N8N_WEBHOOK_URL}/{name}"
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code in (200, 201):
                try:
                    data = resp.json()
                except Exception:
                    data = {"raw": resp.text}
                return {"success": True, "workflow": name, "result": data}
            else:
                return {
                    "success": False,
                    "error": f"n8n webhook returned HTTP {resp.status_code}: {resp.text[:300]}",
                }
    except Exception as exc:
        return {
            "success": False,
            "error": f"Failed to trigger n8n workflow '{name}': {str(exc)}",
        }
