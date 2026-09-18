import os
import db
import ast
import re
from html.parser import HTMLParser

class SimpleHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.classes = set()
        self.tags = set()

    def handle_starttag(self, tag, attrs):
        self.tags.add(tag)
        for attr, value in attrs:
            if attr == "id":
                self.ids.add(value)
            elif attr == "class":
                for cls in value.split():
                    self.classes.add(cls)

def build_file_manifest(workspace_dir: str) -> list[dict]:
    """Walk the workspace directory and build a file manifest."""
    manifest = []
    if not os.path.exists(workspace_dir):
        return manifest
        
    for root, dirs, files in os.walk(workspace_dir):
        # Skip hidden directories and pycache
        dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']
        for file in files:
            if file.startswith('.'):
                continue
            
            filepath = os.path.join(root, file)
            rel_path = os.path.relpath(filepath, workspace_dir)
            try:
                stat = os.stat(filepath)
                ext = os.path.splitext(file)[1].lower()
                manifest.append({
                    "path": rel_path.replace("\\", "/"),
                    "size_bytes": stat.st_size,
                    "last_modified": stat.st_mtime,
                    "extension": ext
                })
            except OSError:
                pass
    return manifest

def extract_structural_map(workspace_dir: str) -> dict:
    """Extract a lightweight structural map per file in the workspace."""
    structural_map = {}
    if not os.path.exists(workspace_dir):
        return structural_map
        
    for root, dirs, files in os.walk(workspace_dir):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']
        for file in files:
            if file.startswith('.'):
                continue
                
            filepath = os.path.join(root, file)
            rel_path = os.path.relpath(filepath, workspace_dir).replace("\\", "/")
            ext = os.path.splitext(file)[1].lower()
            
            if ext == ".db" or ext == ".sqlite":
                try:
                    rows = db.execute_query(filepath, "SELECT name, sql FROM sqlite_master WHERE type='table'")
                    tables = {row["name"]: row["sql"] for row in rows}
                    structural_map[rel_path] = {"type": "sqlite", "tables": tables}
                except Exception:
                    structural_map[rel_path] = {"type": "sqlite", "status": "unindexed"}
                    
            elif ext == ".py":
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        tree = ast.parse(f.read(), filename=filepath)
                    classes = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
                    functions = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
                    structural_map[rel_path] = {"type": "python", "classes": classes, "functions": functions}
                except Exception:
                    structural_map[rel_path] = {"type": "python", "status": "unindexed"}
                    
            elif ext in (".js", ".ts", ".jsx", ".tsx"):
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        content = f.read()
                    # Basic regex extraction
                    functions = re.findall(r'(?:function\s+([a-zA-Z0-9_]+))|(?:const\s+([a-zA-Z0-9_]+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[a-zA-Z0-9_]+)\s*=>)', content)
                    # Flatten and filter out empty matches
                    func_names = [f[0] or f[1] for f in functions if f[0] or f[1]]
                    classes = re.findall(r'class\s+([a-zA-Z0-9_]+)', content)
                    structural_map[rel_path] = {"type": "javascript", "classes": classes, "functions": func_names}
                except Exception:
                    structural_map[rel_path] = {"type": "javascript", "status": "unindexed"}
                    
            elif ext == ".html":
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        content = f.read()
                    parser = SimpleHTMLParser()
                    parser.feed(content)
                    structural_map[rel_path] = {
                        "type": "html", 
                        "ids": list(parser.ids), 
                        "classes": list(parser.classes),
                        "tags": list(parser.tags)
                    }
                except Exception:
                    structural_map[rel_path] = {"type": "html", "status": "unindexed"}
                    
            elif ext == ".css":
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        content = f.read()
                    classes = re.findall(r'\.([a-zA-Z0-9_-]+)\s*\{', content)
                    ids = re.findall(r'#([a-zA-Z0-9_-]+)\s*\{', content)
                    structural_map[rel_path] = {"type": "css", "classes": classes, "ids": ids}
                except Exception:
                    structural_map[rel_path] = {"type": "css", "status": "unindexed"}
                    
    return structural_map
