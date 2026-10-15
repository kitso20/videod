"""viDeoD - local video downloader web app."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .downloader import DOWNLOAD_DIR, manager

app = FastAPI(title="viDeoD")
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@app.get("/api/health")
def health():
    return {"status": "ok"}


class ProbeRequest(BaseModel):
    url: str
    cookies_from_browser: str | None = None


class DownloadRequest(BaseModel):
    url: str
    mode: str = "video"
    quality: str = "1080"


@app.post("/api/probe")
def probe(req: ProbeRequest):
    if not req.url.strip():
        raise HTTPException(400, "URL is required")
    try:
        return manager.probe(req.url.strip(), req.cookies_from_browser)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, str(exc).splitlines()[0][:300]) from exc


@app.post("/api/download")
def start_download(req: DownloadRequest):
    if not req.url.strip():
        raise HTTPException(400, "URL is required")
    if req.mode not in ("video", "audio"):
        raise HTTPException(400, "mode must be 'video' or 'audio'")
    task = manager.enqueue(req.url.strip(), req.mode, req.quality)
    return task.to_dict()


@app.post("/api/tasks/{task_id}/cancel")
def cancel(task_id: str):
    if not manager.cancel(task_id):
        raise HTTPException(404, "Task not found or already finished")
    return {"ok": True}


@app.get("/api/tasks")
def list_tasks():
    return manager.list_tasks()


@app.delete("/api/tasks/{task_id}")
def remove_task(task_id: str):
    task = manager.get(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    if task.status not in ("done", "error", "canceled"):
        raise HTTPException(400, "Task still active")
    manager.tasks.pop(task_id, None)
    return {"ok": True}


@app.get("/api/events")
async def events():
    async def stream():
        while True:
            payload = json.dumps(manager.list_tasks())
            yield f"data: {payload}\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/files/{filename}")
def get_file(filename: str):
    path = DOWNLOAD_DIR / filename
    if not path.resolve().is_relative_to(DOWNLOAD_DIR.resolve()) or not path.is_file():
        raise HTTPException(404, "File not found")
    return FileResponse(path, filename=filename, media_type="application/octet-stream")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
