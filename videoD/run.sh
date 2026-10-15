#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet -r requirements.txt

echo "viDeoD running at http://127.0.0.1:8765"
exec ./.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8765 "$@"
