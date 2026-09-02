import asyncio
import httpx
import os
import shutil
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Any

app = FastAPI(title="Webapp Orchestrator API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Active websocket connections for logs
active_connections: List[WebSocket] = []

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        active_connections.remove(websocket)

async def broadcast(message: dict):
    for connection in active_connections:
        try:
            await connection.send_json(message)
        except Exception:
            pass

class FeatureRequest(BaseModel):
    request: str

AGENT_URLS = {
    "planner-agent": "http://localhost:8010/plan",
    "rag-agent": "http://localhost:8011/query",
    "db-agent": "http://localhost:8012/generate",
    "db-executor": "http://localhost:8013/execute",
    "codegen-agent": "http://localhost:8014/generate",
    "reviewer-agent": "http://localhost:8015/review"
}

async def call_agent(agent_name: str, payload: dict) -> dict:
    url = AGENT_URLS.get(agent_name)
    if not url:
        raise ValueError(f"Unknown agent: {agent_name}")
    
    async with httpx.AsyncClient(timeout=300) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        return response.json()

@app.post("/request")
async def process_request(req: FeatureRequest):
    request_id = os.urandom(4).hex()
    await broadcast({"type": "start", "request_id": request_id, "request": req.request})
    
    # 1. Planner
    await broadcast({"type": "log", "agent": "Planner", "message": "Planning tasks..."})
    try:
        plan = await call_agent("planner-agent", {"feature_request": req.request, "offline": True})
        await broadcast({"type": "log", "agent": "Planner", "message": "Plan generated.", "data": plan})
    except Exception as e:
        await broadcast({"type": "log", "agent": "Planner", "message": f"Planner failed: {str(e)}", "status": "error"})
        return {"status": "error", "message": str(e)}

    subtasks = plan.get("subtasks", [])
    
    context_str = ""
    last_codegen_artifact = None

    for task in subtasks:
        agent = task["agent"]
        desc = task["description"]
        await broadcast({"type": "log", "agent": agent, "message": f"Executing subtask: {desc}"})
        
        try:
            if agent == "system":
                # Handle cleanup or system commands securely
                target_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "target-app"))
                if os.path.exists(target_path):
                    for filename in os.listdir(target_path):
                        file_path = os.path.join(target_path, filename)
                        try:
                            if os.path.isfile(file_path) or os.path.islink(file_path):
                                os.unlink(file_path)
                            elif os.path.isdir(file_path):
                                shutil.rmtree(file_path)
                            # Notify frontend about deletion
                            await broadcast({"type": "file_delete", "filename": filename})
                        except Exception as e:
                            await broadcast({"type": "log", "agent": agent, "message": f"Failed to delete {file_path}: {e}", "status": "error"})
                
                await broadcast({"type": "log", "agent": agent, "message": "Project directory cleaned up."})
                
            elif agent == "rag-agent":
                res = await call_agent("rag-agent", {"description": desc, "top_k": 5})
                context_str += f"\nRAG Context: {res.get('answer', '')}"
                await broadcast({"type": "log", "agent": agent, "message": "Retrieved context.", "data": res})
                
            elif agent == "db-agent":
                res = await call_agent("db-agent", {"description": desc, "offline": True})
                await broadcast({"type": "log", "agent": agent, "message": "Generated query.", "data": res})
                
                query = res.get("query")
                params = res.get("parameters", [])
                if query:
                    await broadcast({"type": "log", "agent": "DB Executor", "message": f"Executing query: {query}"})
                    exec_res = await call_agent("db-executor", {"query": query, "parameters": params})
                    await broadcast({"type": "log", "agent": "DB Executor", "message": "Query executed.", "data": exec_res})
                    
            elif agent == "codegen-agent":
                res = await call_agent("codegen-agent", {"description": desc, "context": context_str, "offline": True})
                await broadcast({"type": "log", "agent": agent, "message": "Code generated.", "data": res})
                
                artifact = res.get("artifact", {})
                last_codegen_artifact = artifact
                code = artifact.get("code")
                filename = artifact.get("filename") or artifact.get("name", "generated.py")
                
                # In offline mode, the codegen-agent always defaults to .py (or .jsx)
                # We enforce the correct filenames if we detect web extensions in the prompt desc
                desc_lower = desc.lower()
                if "html" in desc_lower:
                    filename = "index.html"
                elif "css" in desc_lower:
                    filename = "styles.css"
                elif "js" in desc_lower or "script.js" in desc_lower:
                    filename = "script.js"
                
                if code:
                    target_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "target-app", filename))
                    os.makedirs(os.path.dirname(target_path), exist_ok=True)
                    with open(target_path, "w", encoding="utf-8") as f:
                        f.write(code)
                    await broadcast({"type": "log", "agent": "System", "message": f"Wrote file {filename} to target-app/"})
                    # Trigger a file explorer refresh event
                    await broadcast({"type": "file_update", "filename": filename, "path": target_path})
                    
            elif agent == "reviewer-agent":
                if last_codegen_artifact:
                    req_payload = {"artifact": last_codegen_artifact}
                else:
                    req_payload = {"code": "# No code generated", "language": "python"}
                
                res = await call_agent("reviewer-agent", req_payload)
                verdict = res.get("verdict", "")
                await broadcast({"type": "log", "agent": agent, "message": f"Review complete. Verdict: {verdict}", "data": res})
                
        except Exception as e:
            await broadcast({"type": "log", "agent": agent, "message": f"Failed: {str(e)}", "status": "error"})
            
    await broadcast({"type": "done", "request_id": request_id})
    return {"status": "success"}

# --- File Explorer Endpoints ---

def get_dir_structure(path: str) -> dict:
    name = os.path.basename(path)
    if os.path.isdir(path):
        return {
            "name": name,
            "type": "folder",
            "path": path,
            "children": [get_dir_structure(os.path.join(path, child)) for child in os.listdir(path) if not child.startswith(".")]
        }
    else:
        return {
            "name": name,
            "type": "file",
            "path": path
        }

@app.get("/files")
def get_files():
    target_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "target-app"))
    if not os.path.exists(target_path):
        os.makedirs(target_path, exist_ok=True)
    return get_dir_structure(target_path)

@app.get("/file")
def get_file_content(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return {"content": f.read()}
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8020, reload=True)
