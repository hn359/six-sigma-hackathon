#!/bin/bash
# testme.sh - run the tests, then start the tool on http://localhost:8000
# Run from anywhere: ./app/testme.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install -q -r app/requirements.txt

.venv/bin/python -m pytest -q tests
echo "Open http://localhost:8000 (Ctrl+C to stop)"
.venv/bin/python -m uvicorn app.app:app --host 0.0.0.0 --port 8000
