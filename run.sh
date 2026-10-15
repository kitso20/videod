#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

./.venv/bin/python -m pip install --quiet --upgrade pip
./.venv/bin/python -m pip install --quiet -r requirements.txt

echo "viDeoD running at http://127.0.0.1:8765"
exec ./.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8765 "$@"
