#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

require_command() {
  local command_name="$1"
  local install_hint="$2"

  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Missing required command: $command_name"
    echo "$install_hint"
    exit 1
  fi
}

require_command uv "Install uv first: https://docs.astral.sh/uv/getting-started/installation/"
require_command docker "Install Docker Desktop or another Docker engine with Docker Compose support."

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose is required. Ensure 'docker compose' is available."
  exit 1
fi

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example."
fi

echo "Installing Python dependencies with uv..."
uv sync --extra dev

echo "Starting PostgreSQL with Docker Compose..."
docker compose up -d postgres

echo "Applying database migrations..."
uv run python scripts/migrate.py

echo "Bootstrap complete."
echo "Next steps:"
echo "  1. Ensure Ollama is running and the configured chat/embed models are available."
echo "  2. Start the app with: uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
