import os
import re
import subprocess
import copy

def run_preflight_checks(plan: dict, manifest: list, structural_map: dict, workspace: str) -> dict:
    """Run pre-flight checks on the plan and augment it with status."""
    augmented_plan = copy.deepcopy(plan)
    subtasks = augmented_plan.get("subtasks", [])
    
    # Pre-compute simple lists of existing symbols for collision detection
    existing_symbols = set()
    for rel_path, data in structural_map.items():
        if data.get("type") == "sqlite" and "tables" in data:
            existing_symbols.update(data["tables"].keys())
        elif data.get("type") == "javascript":
            existing_symbols.update(data.get("functions", []))
            existing_symbols.update(data.get("classes", []))
        elif data.get("type") == "python":
            existing_symbols.update(data.get("functions", []))
            existing_symbols.update(data.get("classes", []))
    
    # Pre-compute existing files
    existing_files = {f["path"] for f in manifest}
    
    # Pre-compute dependencies (Python)
    existing_deps = set()
    req_path = os.path.join(workspace, "requirements.txt")
    if os.path.exists(req_path):
        try:
            with open(req_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip().split("==")[0].lower()
                    if line:
                        existing_deps.add(line)
        except Exception:
            pass

    new_subtasks = []
    
    for task in subtasks:
        task["preflight_status"] = "ok"
        task["preflight_details"] = ""
        
        agent = task.get("agent")
        desc = task.get("description", "").lower()
        
        # 1. File-Exists Check
        if agent == "codegen-agent" and task.get("target_filename"):
            if task["target_filename"] in existing_files:
                task["preflight_status"] = "warning"
                task["preflight_details"] = f"File '{task['target_filename']}' already exists. Overwrite?"
                try:
                    with open(os.path.join(workspace, task["target_filename"]), "r", encoding="utf-8") as fh:
                        task["preflight_old_content"] = fh.read()
                except Exception:
                    pass
        
        # 2. Naming / Route Collision Check
        # Basic heuristic: if the description mentions an existing symbol exactly.
        if agent in ("codegen-agent", "db-agent"):
            words = set(re.findall(r'\b[a-zA-Z0-9_]+\b', desc))
            collisions = words.intersection(existing_symbols)
            # Filter out generic words
            generic = {"app", "user", "id", "script", "style"}
            collisions = collisions - generic
            if collisions:
                if task["preflight_status"] == "ok":
                    task["preflight_status"] = "warning"
                task["preflight_details"] += f" Possible symbol collision with existing: {', '.join(collisions)}."
        
        # 3. Environment Check
        if agent == "system":
            if "npm" in desc:
                res = subprocess.run(["npm", "-v"], capture_output=True, shell=True)
                if res.returncode != 0:
                    task["preflight_status"] = "blocked"
                    task["preflight_details"] = "npm is not installed or unreachable."
            elif "docker" in desc:
                res = subprocess.run(["docker", "info"], capture_output=True, shell=True)
                if res.returncode != 0:
                    task["preflight_status"] = "blocked"
                    task["preflight_details"] = "Docker daemon is not running."
            elif "python" in desc or "pip" in desc:
                res = subprocess.run(["python", "--version"], capture_output=True, shell=True)
                if res.returncode != 0:
                    task["preflight_status"] = "blocked"
                    task["preflight_details"] = "Python is not installed or unreachable."
                    
        # 4. Dependency Check
        # Check if they mention a known framework that isn't in requirements.
        common_deps = {"flask", "fastapi", "requests", "react", "express"}
        missing = []
        for dep in common_deps:
            if dep in desc and dep not in existing_deps:
                missing.append(dep)
        
        if missing:
            # We add an explicit dependency injection step BEFORE this task.
            install_task = {
                "task_id": f"install_{task['task_id']}",
                "agent": "system",
                "description": f"pip install {', '.join(missing)}",
                "dependencies": list(task.get("dependencies", [])),
                "preflight_status": "ok",
                "preflight_details": f"Auto-injected by pre-flight check to satisfy missing dependencies: {', '.join(missing)}",
                "is_injected": True
            }
            new_subtasks.append(install_task)
            # Update this task's dependencies
            task["dependencies"].append(install_task["task_id"])
            existing_deps.update(missing) # Assume installed for subsequent tasks
            
        # 5. Schema Drift Check (DB Agent)
        if agent == "db-agent":
            # Just attach the real schema to the task data so the UI can flag drift if needed
            real_schema = []
            for rel_path, data in structural_map.items():
                if data.get("type") == "sqlite" and "tables" in data:
                    real_schema.append(data["tables"])
            if real_schema:
                task["real_db_schema"] = real_schema

        new_subtasks.append(task)
        
    augmented_plan["subtasks"] = new_subtasks
    return augmented_plan
