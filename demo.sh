#!/bin/bash
# demo.sh - start the Bikeshare Dispatch demo with one command, from a fresh clone.
#   ./demo.sh          then open http://localhost:8000
# Needs Python 3.11+ and Node.js 20+. Installs into .venv and app/frontend/node_modules,
# builds the map, and serves the home page (About, Map and dispatch, Redistribution, SPC charts).
# The tests are separate: ./app/testme.sh

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
PORT="${PORT:-8000}"

command -v python3 >/dev/null || { echo "Python 3.11+ is needed: https://www.python.org/downloads/"; exit 1; }
command -v npm >/dev/null || { echo "Node.js 20+ is needed: https://nodejs.org/"; exit 1; }

echo "1/3 Python packages ..."
[ -d .venv ] || python3 -m venv .venv
PY=.venv/bin/python
[ -x "$PY" ] || PY=.venv/Scripts/python.exe   # Windows (Git Bash)
"$PY" -m pip install -q -r app/requirements.txt -r app/bikeflow/requirements.txt

echo "2/3 Building the map ..."
(cd app/frontend && npm ci --silent && npm run build --silent)

echo "3/3 Starting: open http://localhost:${PORT}   (Ctrl+C to stop)"
"$PY" -m uvicorn app.bikeflow.combined:app --host 127.0.0.1 --port "$PORT"
