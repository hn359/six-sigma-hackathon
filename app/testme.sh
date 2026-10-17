#!/bin/bash
# testme.sh - one command: install, run every test, build the React console, start the tool.
# Run from anywhere: ./app/testme.sh   then open http://localhost:${PORT:-8000}

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

[ -d .venv ] || python3 -m venv .venv
.venv/bin/python -m pip install -q -r app/requirements.txt
.venv/bin/python -m pytest -q tests

(cd app/frontend && npm ci --silent && npx vitest run && npm run build)

echo "Open http://localhost:${PORT:-8000}  (API docs at /docs; Ctrl+C to stop)"
.venv/bin/python -m uvicorn app.app:app --host 0.0.0.0 --port "${PORT:-8000}"
