#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .env ]]; then
  cp .env.example .env
fi

uv sync --extra dev
docker compose up -d postgres
uv run python scripts/migrate.py

echo "Bootstrap complete."
echo "Start the app with: uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
