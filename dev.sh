#!/usr/bin/env bash
# One command to run the full local stack: the external order/FAQ service
# (:8100) and the agent (:8000). Kept as two processes deliberately -- see
# README's "Integration boundary" section -- this script just saves you two
# terminals, it doesn't change the architecture.
set -euo pipefail
cd "$(dirname "$0")"

# No python-dotenv auto-load in the app on purpose (see README's Logging
# section) -- load .env into this shell so both child processes inherit it.
if [ -f .env ]; then
  set -a && source .env && set +a
fi

trap 'kill 0' EXIT

uvicorn external_service.main:app --port 8100 --reload &
uvicorn app.channels.web:app --port 8000 --reload &

wait
