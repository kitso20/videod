"""viDeoD - local video downloader web app."""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.background import BackgroundTask

from .downloader import DOWNLOAD_DIR, STREAM_DIR, manager

app = FastAPI(title="viDeoD")
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

_CID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

_ALLOWED_BROWSERS = {"brave", "chrome", "chromium", "edge", "firefox", "opera", "safari", "vivaldi", "whale"}


def _unlink_quiet(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _client_id(request: Request, query_param: str = "cid") -> str:
    """Resolve the calling device id (header for fetch, query for EventSource)."""
    raw = request.headers.get("X-Client-Id") or request.query_params.get(query_param) or ""
    raw = raw.strip()
    if raw and not _CID_RE.match(raw):
        raise HTTPException(400, "Invalid client id")
    return raw


def _owned_task(task_id: str, client_id: str):
    task = manager.get(task_id)
    if not task or task.client_id != client_id:
        raise HTTPException(404, "Task not found")
    return task


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
    cookies_from_browser: str | None = None


@app.post("/api/probe")
def probe(req: ProbeRequest):
    if not req.url.strip():
        raise HTTPException(400, "URL is required")
    cfb = (req.cookies_from_browser or "").strip()
    if cfb and cfb not in _ALLOWED_BROWSERS:
        raise HTTPException(400, f"Unsupported browser: {cfb}")
    try:
        return manager.probe(req.url.strip(), cfb or None)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, str(exc).splitlines()[0][:300]) from exc


@app.post("/api/download")
def start_download(req: DownloadRequest, request: Request):
    if not req.url.strip():
        raise HTTPException(400, "URL is required")
    if req.mode not in ("video", "audio"):
        raise HTTPException(400, "mode must be 'video' or 'audio'")
    cfb = (req.cookies_from_browser or "").strip()
    if cfb and cfb not in _ALLOWED_BROWSERS:
        raise HTTPException(400, f"Unsupported browser: {cfb}")
    task = manager.enqueue(
        req.url.strip(),
        req.mode,
        req.quality,
        _client_id(request),
        cfb,
    )
    return task.to_dict()


@app.post("/api/tasks/{task_id}/cancel")
def cancel(task_id: str, request: Request):
    _owned_task(task_id, _client_id(request))
    if not manager.cancel(task_id):
        raise HTTPException(404, "Task not found or already finished")
    return {"ok": True}


@app.get("/api/tasks")
def list_tasks(request: Request):
    return manager.list_tasks(_client_id(request))


@app.delete("/api/tasks/{task_id}")
def remove_task(task_id: str, request: Request):
    task = _owned_task(task_id, _client_id(request))
    if task.status not in ("done", "error", "canceled"):
        raise HTTPException(400, "Task still active")
    manager.tasks.pop(task_id, None)
    if task.filename:
        _unlink_quiet(STREAM_DIR / task.filename)
    return {"ok": True}


@app.get("/api/events")
async def events(request: Request):
    client_id = _client_id(request)

    async def stream():
        while True:
            payload = json.dumps(manager.list_tasks(client_id))
            yield f"data: {payload}\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/files/{filename}")
def get_file(filename: str, request: Request):
    client_id = _client_id(request)
    owners = {t.client_id for t in manager.tasks.values() if t.filename == filename}
    if owners and client_id not in owners:
        raise HTTPException(404, "File not found")
    stream_path = STREAM_DIR / filename
    if stream_path.is_file() and stream_path.resolve().is_relative_to(STREAM_DIR.resolve()):
        return FileResponse(
            stream_path,
            filename=filename,
            media_type="application/octet-stream",
            background=BackgroundTask(_unlink_quiet, stream_path),
        )
    legacy = DOWNLOAD_DIR / filename
    if legacy.is_file() and legacy.resolve().is_relative_to(DOWNLOAD_DIR.resolve()):
        return FileResponse(legacy, filename=filename, media_type="application/octet-stream")
    raise HTTPException(404, "File not found")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
