"""Serve the default generated workspace for the pipeline launcher."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

APP_DIR = Path(__file__).resolve().parent
app = FastAPI(title="Generated Target App")
app.mount("/static", StaticFiles(directory=APP_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """Return the generated entry point when available."""
    index_path = APP_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return FileResponse(APP_DIR / "app.py", media_type="text/plain")


@app.get("/health")
def health() -> dict[str, str]:
    """Return target app health."""
    return {"status": "ok", "service": "target-app"}
