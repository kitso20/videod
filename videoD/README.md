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

## Configuration

| Env var        | Default              | Purpose                                                        |
| -------------- | -------------------- | -------------------------------------------------------------- |
| `DOWNLOAD_DIR` | `videoD/downloads`   | Where downloaded files are stored.                             |
| `COOKIES_FILE` | —                    | Path to a Netscape `cookies.txt` (for bot/login-gated sites).  |
| `COOKIES_B64`  | —                    | Base64-encoded `cookies.txt`; useful on hosts with no disk.    |

No accounts, no ads, no trackers — it's a deliberately minimal self-hosted tool.

## Deploy (Render)

This is a **web service**, not a static site (it runs Python + ffmpeg).

- Easiest: `New +` → **Blueprint** → pick this repo. `render.yaml` provisions a
  Docker web service automatically.
- Manual: `New +` → **Web Service** → Runtime **Docker**, Root Directory `videoD`,
  Dockerfile Path `videoD/Dockerfile`.

The container installs ffmpeg and listens on `$PORT` with a `/api/health` check.

## CI/CD

`.github/workflows/deploy.yml` runs on every push/PR to `main`:

1. **test** — installs deps, imports the app, hits `/api/health`, builds the image.
2. **publish** — pushes the image to GHCR (`ghcr.io/<owner>/<repo>/videod`).
3. **deploy** — calls a Render deploy hook, if the `RENDER_DEPLOY_HOOK` secret is set.

To enable deploys: Render service → **Settings → Deploy Hook**, copy the URL, then
add it as a repo secret named `RENDER_DEPLOY_HOOK`.
(If you connect the repo directly in Render, Render already auto-deploys on push
and you can ignore the deploy job.)

## Notes

- Keep `yt-dlp` up to date (`./.venv/bin/pip install -U yt-dlp`); sites change often.
- YouTube blocks most datacenter IPs ("sign in to confirm you're not a bot"). On a
  server, export cookies from a logged-in browser to `cookies.txt` and set
  `COOKIES_FILE`/`COOKIES_B64`. Locally it usually works without them.
- On Render's free plan the disk is ephemeral, so downloads disappear on
  restart/redeploy. Add a persistent disk if you need a lasting store.
- Only download content you have the right to.
