"""yt-dlp wrapper: metadata probing, background download queue and progress."""
from __future__ import annotations

import base64
import os
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from queue import Queue
from typing import Any

import yt_dlp

try:  # bundled static ffmpeg only when no system ffmpeg is available
    if shutil.which("ffmpeg") is None:
        import static_ffmpeg

        static_ffmpeg.add_paths()
except Exception:  # noqa: BLE001
    pass

BASE_DIR = Path(__file__).resolve().parent.parent
DOWNLOAD_DIR = Path(os.environ.get("DOWNLOAD_DIR", BASE_DIR / "downloads"))
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Files live here only between "download finished" and "streamed to the device
# that asked for it" — the server keeps no copy afterwards.
STREAM_DIR = Path(os.environ.get("STREAM_DIR", DOWNLOAD_DIR / ".stream"))
STREAM_DIR.mkdir(parents=True, exist_ok=True)
for _leftover in STREAM_DIR.iterdir():
    try:
        _leftover.unlink()
    except OSError:
        pass


def _cookie_opts() -> dict[str, Any]:
    """Resolve yt-dlp cookie options from env.

    COOKIES_FILE: path to a Netscape cookie file.
    COOKIES_B64:  base64-encoded Netscape cookie file (written to a temp file).
    """
    path = os.environ.get("COOKIES_FILE", "").strip()
    if not path and os.environ.get("COOKIES_B64"):
        target = Path(os.environ.get("TMPDIR", "/tmp")) / "videod_cookies.txt"
        try:
            target.write_bytes(base64.b64decode(os.environ["COOKIES_B64"]))
            path = str(target)
        except Exception:  # noqa: BLE001
            path = ""
    return {"cookiefile": path} if path and Path(path).is_file() else {}

AUDIO_QUALITIES = ["128", "192", "256", "320"]


def _has_ffmpeg() -> bool:
    """True when an ffmpeg binary is reachable (system, bundled, or static)."""
    return shutil.which("ffmpeg") is not None


def _yt_net_opts() -> dict[str, Any]:
    """Pin requests to IPv4 to dodge YouTube's IPv6-range bot checks.

    Some ISPs' IPv6 ranges are flagged, so binding the source address to
    ``0.0.0.0`` (what ``--force-ipv4`` does) avoids "Sign in to confirm you're
    not a bot" without needing cookies. We deliberately leave yt-dlp's default
    player clients alone: forcing ``android`` would break cookie auth (that
    client does not support cookies) and require a PO token.
    """
    return {"source_address": "0.0.0.0"}


QUALITY_PRESETS = [
    {"id": "2160", "label": "4K (2160p)", "height": 2160},
    {"id": "1440", "label": "2K (1440p)", "height": 1440},
    {"id": "1080", "label": "Full HD (1080p)", "height": 1080},
    {"id": "720", "label": "HD (720p)", "height": 720},
    {"id": "480", "label": "SD (480p)", "height": 480},
    {"id": "360", "label": "Low (360p)", "height": 360},
    {"id": "best", "label": "Best available", "height": None},
]


@dataclass
class Task:
    id: str
    url: str
    mode: str  # "video" | "audio"
    quality: str
    client_id: str = ""  # owning device; tasks are only visible to that device
    cookies_from_browser: str = ""  # browser name for yt-dlp cookie auth
    title: str = "Fetching..."
    thumbnail: str = ""
    status: str = "queued"  # queued | downloading | processing | done | error | canceled
    progress: float = 0.0
    speed: str = ""
    eta: str = ""
    filename: str = ""
    filesize: int = 0
    error: str = ""
    created: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "url": self.url,
            "mode": self.mode,
            "quality": self.quality,
            "title": self.title,
            "thumbnail": self.thumbnail,
            "status": self.status,
            "progress": round(self.progress, 2),
            "speed": self.speed,
            "eta": self.eta,
            "filename": self.filename,
            "filesize": self.filesize,
            "error": self.error,
            "created": self.created,
        }


def _fmt(speed: float | None, eta: int | None) -> tuple[str, str]:
    sp = f"{speed / 1024 / 1024:.2f} MB/s" if speed else ""
    if eta is None:
        et = ""
    else:
        m, s = divmod(int(eta), 60)
        h, m = divmod(m, 60)
        et = f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"
    return sp, et


class DownloadManager:
    def __init__(self) -> None:
        self.tasks: dict[str, Task] = {}
        self.queue: Queue[str] = Queue()
        self._lock = threading.Lock()
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    # ---------- metadata ----------
    def probe(self, url: str, cookies_from_browser: str | None = None) -> dict[str, Any]:
        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": True,
        }
        opts.update(_cookie_opts())
        if cookies_from_browser:
            opts["cookiesfrombrowser"] = (cookies_from_browser,)
        opts.update(_yt_net_opts())
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

        heights = sorted(
            {
                f.get("height")
                for f in info.get("formats", [])
                if f.get("height") and f.get("vcodec") not in (None, "none")
            },
            reverse=True,
        )
        available = [q for q in QUALITY_PRESETS if q["height"] is None or q["height"] in heights]
        if not available:
            available = [QUALITY_PRESETS[-1]]

        return {
            "title": info.get("title") or "Untitled",
            "thumbnail": info.get("thumbnail") or "",
            "duration": info.get("duration"),
            "uploader": info.get("uploader") or info.get("channel") or "",
            "extractor": info.get("extractor_key") or info.get("extractor") or "",
            "is_live": bool(info.get("is_live")),
            "qualities": available,
            "audio_qualities": AUDIO_QUALITIES,
        }

    # ---------- queue ----------
    def enqueue(
        self,
        url: str,
        mode: str,
        quality: str,
        client_id: str = "",
        cookies_from_browser: str = "",
    ) -> Task:
        task = Task(
            id=uuid.uuid4().hex[:12],
            url=url,
            mode=mode,
            quality=quality,
            client_id=client_id,
            cookies_from_browser=cookies_from_browser,
        )
        with self._lock:
            self.tasks[task.id] = task
        self.queue.put(task.id)
        return task

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            task = self.tasks.get(task_id)
            if not task or task.status in ("done", "error", "canceled"):
                return False
            task.status = "canceled"
            return True

    def list_tasks(self, client_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            tasks = self.tasks.values()
            if client_id is not None:
                tasks = [t for t in tasks if t.client_id == client_id]
            return [t.to_dict() for t in sorted(tasks, key=lambda x: x.created, reverse=True)]

    def get(self, task_id: str) -> Task | None:
        with self._lock:
            return self.tasks.get(task_id)

    # ---------- worker ----------
    def _run(self) -> None:
        while True:
            task_id = self.queue.get()
            task = self.get(task_id)
            if not task or task.status == "canceled":
                continue
            try:
                self._download(task)
            except Exception as exc:  # noqa: BLE001
                task.status = "error"
                task.error = str(exc).splitlines()[0][:300]

    def _download(self, task: Task) -> None:
        outtmpl = str(STREAM_DIR / "%(title).150B [%(id)s].%(ext)s")

        def hook(d: dict[str, Any]) -> None:
            if task.status == "canceled":
                raise yt_dlp.utils.DownloadError("canceled")
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                done = d.get("downloaded_bytes") or 0
                task.status = "downloading"
                if total:
                    task.progress = done / total * 100
                    task.filesize = int(total)
                task.speed, task.eta = _fmt(d.get("speed"), d.get("eta"))
            elif d.get("status") == "finished":
                task.progress = 100.0
                task.status = "processing"

        opts: dict[str, Any] = {
            "outtmpl": outtmpl,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [hook],
            "postprocessor_hooks": [lambda d: setattr(task, "status", "processing")],
            "paths": {"home": str(STREAM_DIR)},
        }
        opts.update(_cookie_opts())
        if task.cookies_from_browser:
            opts["cookiesfrombrowser"] = (task.cookies_from_browser,)
        opts.update(_yt_net_opts())

        have_ffmpeg = _has_ffmpeg()
        if task.mode == "audio":
            if have_ffmpeg:
                opts["format"] = "bestaudio/best"
                opts["postprocessors"] = [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": task.quality or "192",
                    }
                ]
            else:
                # No ffmpeg: save a directly-playable AAC (m4a) stream.
                opts["format"] = "bestaudio[ext=m4a]/bestaudio/best"
        else:
            h = task.quality
            if not have_ffmpeg:
                # No ffmpeg: only single-stream formats are usable; prefer MP4.
                if h == "best":
                    opts["format"] = "best[ext=mp4]/best"
                else:
                    opts["format"] = f"best[height<={h}][ext=mp4]/best[height<={h}]/best"
            elif h == "best":
                opts["format"] = "bestvideo+bestaudio/best"
                opts["merge_output_format"] = "mp4"
            else:
                opts["format"] = (
                    f"bestvideo[height<={h}]+bestaudio/best[height<={h}]/best"
                )
                opts["merge_output_format"] = "mp4"

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(task.url, download=True)
            if not task.title or task.title == "Fetching...":
                task.title = info.get("title") or task.title
            if not task.thumbnail:
                task.thumbnail = info.get("thumbnail") or ""
            path = ydl.prepare_filename(info)
            if not Path(path).exists():
                for ext in (".mp3", ".mp4", ".mkv", ".webm", ".m4a", ".opus", ".ogg"):
                    cand = Path(path).with_suffix(ext)
                    if cand.exists():
                        path = str(cand)
                        break
            task.filename = Path(path).name
            task.filesize = Path(path).stat().st_size if Path(path).exists() else task.filesize
            task.progress = 100.0
            task.status = "done"


manager = DownloadManager()
