"""Local HTTP server for viDeoD — stdlib only (FastAPI/pydantic can't run on Android).

Mirrors app/main.py's endpoints so static/app.js works unchanged, and reuses
app/downloader.py's DownloadManager as-is (it only needs yt-dlp).
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
_PORT = 8765
_CID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def _ensure_importable() -> None:
    """Make the `app` package importable (repo checkout or generated source dir)."""
    try:
        import app.downloader  # noqa: F401

        return
    except Exception:  # noqa: BLE001
        pass
    import sys

    d = HERE
    for _ in range(6):
        if os.path.isfile(os.path.join(d, "app", "downloader.py")):
            sys.path.insert(0, d)
            return
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent


def _find_static() -> str:
    for base in (HERE, os.getcwd()):
        cand = os.path.join(base, "static")
        if os.path.isdir(cand):
            return cand
    d = HERE
    for _ in range(6):
        cand = os.path.join(d, "static")
        if os.path.isdir(cand):
            return cand
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return os.path.join(HERE, "static")


_ensure_importable()
from app.downloader import STREAM_DIR, manager  # noqa: E402

STATIC_DIR = _find_static()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "viDeoD"

    # ---------- plumbing ----------
    def log_message(self, fmt: str, *args) -> None:  # keep logcat quiet
        pass

    def _json(self, obj, status: int = 200) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, message: str) -> None:
        self._json({"detail": message}, status)

    def _body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except Exception:  # noqa: BLE001
            return {}
        return data if isinstance(data, dict) else {}

    def _cid(self) -> str:
        raw = (self.headers.get("X-Client-Id") or "").strip()
        if not raw:
            raw = (parse_qs(urlparse(self.path).query).get("cid") or [""])[0].strip()
        if raw and not _CID_RE.match(raw):
            raise ValueError("Invalid client id")
        return raw

    # ---------- static ----------
    def _serve_file(self, path: str, download: bool = False) -> None:
        if not os.path.isfile(path):
            self._error(404, "File not found")
            return
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        size = os.path.getsize(path)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        if download:
            name = os.path.basename(path)
            self.send_header(
                "Content-Disposition",
                'attachment; filename="%s"' % name.replace('"', ""),
            )
        self.end_headers()
        try:
            with open(path, "rb") as fh:
                while True:
                    chunk = fh.read(64 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            return

    # ---------- routes ----------
    def do_GET(self) -> None:  # noqa: N802
        try:
            self._route_get()
        except ValueError as exc:
            self._error(400, str(exc))
        except Exception as exc:  # noqa: BLE001
            self._error(400, str(exc).splitlines()[0][:300])

    def _route_get(self) -> None:
        url = urlparse(self.path)
        path = url.path
        query = parse_qs(url.query)

        if path == "/" or path == "/index.html":
            self._serve_file(os.path.join(STATIC_DIR, "index.html"))
        elif path.startswith("/static/"):
            rel = os.path.normpath(unquote(path[len("/static/") :]))
            if rel.startswith(("..", "/")):
                self._error(404, "Not found")
                return
            self._serve_file(os.path.join(STATIC_DIR, rel))
        elif path == "/api/health":
            self._json({"status": "ok"})
        elif path == "/api/tasks":
            self._json(manager.list_tasks(self._cid()))
        elif path == "/api/events":
            self._sse(self._cid())
        elif path.startswith("/api/files/"):
            name = unquote(path[len("/api/files/") :])
            self._serve_file_download(name)
        else:
            self._error(404, "Not found")

    def _serve_file_download(self, name: str) -> None:
        cid = self._cid()
        owners = {t.client_id for t in manager.tasks.values() if t.filename == name}
        if owners and cid not in owners:
            self._error(404, "File not found")
        target = (STREAM_DIR / name).resolve()
        if not str(target).startswith(str(STREAM_DIR.resolve())) or not target.is_file():
            self._error(404, "File not found")
            return
        try:
            self._serve_file(str(target), download=True)
        finally:
            try:
                target.unlink()
            except OSError:
                pass

    def do_POST(self) -> None:  # noqa: N802
        try:
            self._route_post()
        except ValueError as exc:
            self._error(400, str(exc))
        except Exception as exc:  # noqa: BLE001
            self._error(400, str(exc).splitlines()[0][:300])

    def _route_post(self) -> None:
        path = urlparse(self.path).path
        body = self._body()

        if path == "/api/probe":
            self._probe(body)
        elif path == "/api/download":
            self._download(body)
        elif path.startswith("/api/tasks/") and path.endswith("/cancel"):
            task_id = path[len("/api/tasks/") : -len("/cancel")]
            self._owned_task(task_id)
            if not manager.cancel(task_id):
                self._error(404, "Task not found or already finished")
                return
            self._json({"ok": True})
        else:
            self._error(404, "Not found")

    def do_DELETE(self) -> None:  # noqa: N802
        try:
            path = urlparse(self.path).path
            if not path.startswith("/api/tasks/"):
                self._error(404, "Not found")
                return
            task_id = path[len("/api/tasks/") :]
            task = self._owned_task(task_id)
            if task.status not in ("done", "error", "canceled"):
                self._error(400, "Task still active")
                return
            manager.tasks.pop(task_id, None)
            if task.filename:
                try:
                    (STREAM_DIR / task.filename).unlink()
                except OSError:
                    pass
            self._json({"ok": True})
        except ValueError as exc:
            self._error(400, str(exc))
        except Exception as exc:  # noqa: BLE001
            self._error(400, str(exc).splitlines()[0][:300])

    # ---------- handlers ----------
    def _owned_task(self, task_id: str):
        cid = self._cid()
        task = manager.get(task_id)
        if not task or task.client_id != cid:
            raise KeyError("Task not found")
        return task

    def _probe(self, body: dict) -> None:
        url = (body.get("url") or "").strip()
        if not url:
            self._error(400, "URL is required")
            return
        cfb = (body.get("cookies_from_browser") or "").strip()
        self._json(manager.probe(url, cfb or None))

    def _download(self, body: dict) -> None:
        url = (body.get("url") or "").strip()
        if not url:
            self._error(400, "URL is required")
            return
        mode = body.get("mode") or "video"
        if mode not in ("video", "audio"):
            self._error(400, "mode must be 'video' or 'audio'")
            return
        quality = str(body.get("quality") or "1080")
        cfb = (body.get("cookies_from_browser") or "").strip()
        task = manager.enqueue(url, mode, quality, self._cid(), cfb)
        self._json(task.to_dict())

    def _sse(self, cid: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            while True:
                payload = json.dumps(manager.list_tasks(cid))
                self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                self.wfile.flush()
                time.sleep(1.0)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            self.close_connection = True


_server: ThreadingHTTPServer | None = None
_lock = threading.Lock()


def start(port: int = _PORT) -> int:
    """Bind and serve in a daemon thread; blocks until the socket is listening."""
    global _server
    with _lock:
        if _server is not None:
            return _server.server_address[1]
        srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        srv.daemon_threads = True
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        _server = srv
        return srv.server_address[1]


def stop() -> None:
    global _server
    with _lock:
        if _server is not None:
            _server.shutdown()
            _server = None


if __name__ == "__main__":
    p = start()
    print(f"viDeoD server on http://127.0.0.1:{p}")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop()
