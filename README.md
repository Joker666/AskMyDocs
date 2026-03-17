# AskMyDocs

Phase 1 provides the backend bootstrap for a local PDF question-answering system:

- FastAPI app entrypoint at `app.main:app`
- PostgreSQL + pgvector bootstrap through raw SQL migrations
- Ollama's Anthropic-compatible API for chat/tool-calling and Ollama native endpoints for embeddings
- `GET /health` with app, DB, Anthropic-compat, and Ollama-native status fields

## Prerequisites

- Python 3.13+
- `uv`
- Docker

## Quick Start

1. Copy the example environment file:

   ```bash
   cp .env.example .env
   ```

2. Install dependencies:

   ```bash
   uv sync --extra dev
   ```

3. Start PostgreSQL with pgvector:

   ```bash
   docker compose up -d postgres
   ```

4. Apply migrations:

   ```bash
   uv run python scripts/migrate.py
   ```

5. Run the API:

   ```bash
   uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

6. Check health:

   ```bash
   curl http://127.0.0.1:8000/health
   ```

Expected response when the database is reachable:

```json
{
  "status": "ok",
  "checks": {
    "app": {"status": "ok", "detail": null},
    "db": {"status": "ok", "detail": null},
    "anthropic_compat": {"status": "not_checked", "detail": null},
    "ollama_native": {"status": "not_checked", "detail": null}
  }
}
```

`ANTHROPIC_BASE_URL` and `OLLAMA_BASE_URL` both default to `http://localhost:11434` because they target different endpoint families exposed by the same local Ollama server.

## Bootstrap Script

You can run the same local setup with:

```bash
./scripts/bootstrap.sh
```

The script will:

- create `.env` from `.env.example` if needed
- install dependencies with `uv`
- start Docker Compose PostgreSQL
- apply raw SQL migrations

## Development Checks

Run the local checks with:

```bash
uv run pytest
uv run ruff check .
uv run pyright
```
