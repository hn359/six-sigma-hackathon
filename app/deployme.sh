#!/bin/bash
# deployme.sh

# Deploy FastAPI to Posit Connect using manifest.json.
# This script targets Posit Connect (not Connect Cloud).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

python -m pip install -q rsconnect-python

# Optional: load CONNECT_SERVER and CONNECT_API_KEY from .env
if [ -f ".env" ]; then
  # shellcheck disable=SC1091
  source .env
elif [ -f "../.env" ]; then
  # shellcheck disable=SC1091
  source ../.env
fi

APP_ID="${CONNECT_APP_ID:-17ab3147-debc-48ae-8548-2d63bbba623d}"

echo "Deploying app via manifest to Posit Connect (${CONNECT_SERVER:-default server})..."
rsconnect deploy manifest \
  ${CONNECT_SERVER:+--server "$CONNECT_SERVER"} \
  ${CONNECT_API_KEY:+--api-key "$CONNECT_API_KEY"} \
  ${APP_ID:+--app-id "$APP_ID"} \
  manifest.json
