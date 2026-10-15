# viDeoD

A local web video downloader inspired by Vidmate. Paste a link from anywhere,
pick your quality (or extract MP3), and download to your machine — with a
background queue and live progress.

## Features

- Paste any [yt-dlp supported](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md) link (YouTube, TikTok, Instagram, Twitter/X, Reddit, Facebook, …)
- Fetch video info (title, thumbnail, channel) before downloading
- Quality picker (2160p / 1440p / 1080p / 720p / 480p / 360p / best available)
- Audio-only MP3 extraction (128–320 kbps)
- Background download queue: multiple downloads, live progress, speed, ETA
- Cancel active downloads, remove finished ones, re-download from local store

## Requirements

- Python 3.10+
- ffmpeg — for merging video+audio and MP3 conversion. **No system ffmpeg?**
  The bundled `static-ffmpeg` dependency downloads one automatically on first run.

## Setup & run

```bash
cd videoD
./run.sh
```

Then open <http://127.0.0.1:8765> in your browser.

Or manually:

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8765
```

## How it works

- `app/downloader.py` — yt-dlp wrapper: metadata probe + background worker thread
  with a download queue and progress hooks.
- `app/main.py` — FastAPI endpoints (`/api/probe`, `/api/download`, `/api/tasks`,
  `/api/events` SSE stream, `/api/files/{name}`).
- `static/` — no-build vanilla HTML/CSS/JS front end.

Downloaded files are saved to `downloads/` and served through the app so you can
grab them with the browser's own download.

## Notes

- Keep `yt-dlp` up to date (`./.venv/bin/pip install -U yt-dlp`); sites change often.
- For geo/login-restricted content, yt-dlp can use browser cookies. The API's
  `/api/probe` and downloader accept a `cookies_from_browser` value (e.g. `firefox`,
  `chrome`); wiring this into the UI is a natural next step.
- Only download content you have the right to.
