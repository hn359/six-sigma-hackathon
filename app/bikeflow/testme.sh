#!/bin/bash
# testme.sh - run the BikeFlow tests, then start the dashboard on http://localhost:8000
# Run from anywhere: ./app/bikeflow/testme.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
PY=.venv/bin/python
[ -x "$PY" ] || PY=.venv/Scripts/python.exe   # Windows
"$PY" -m pip install -q -r app/bikeflow/requirements.txt

"$PY" -m pytest -q tests/test_bikeflow.py tests/test_bikeflow_api.py
echo "Open http://localhost:8000 and upload a station CSV (Ctrl+C to stop)"
"$PY" -m uvicorn app.bikeflow.server:app --host 0.0.0.0 --port 8000
