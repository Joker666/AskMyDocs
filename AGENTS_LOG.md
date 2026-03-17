## 2026-03-17 01:24

### Completed

- Bootstrapped the project into the target package layout for Phase 1.
- Added config loading, structured logging, Docker Compose PostgreSQL, raw SQL migrations, and a migration runner.
- Replaced the sample FastAPI scaffold with `app.main:app` and implemented `GET /health` with DB probing plus placeholder checks for Ollama's Anthropic-compatible and native APIs.
- Added initial SQLModel table definitions, bootstrap scripts, and Phase 1 tests.
- Aligned the chat path and docs to Ollama's Anthropic-compatible API and kept Ollama native endpoints for embeddings.

### Files Changed

- .gitignore
- pyproject.toml
- .env.example
- docker-compose.yml
- README.md
- scripts/bootstrap.sh
- scripts/migrate.py
- migrations/001_bootstrap.sql
- app/
- tests/
- AGENTS.md
- AGENTS_LOG.md

### Notes

- The health endpoint actively checks only the database in Phase 1; Ollama compatibility and native endpoint fields remain `not_checked` placeholders.
- The initial schema uses `vector(768)` for `embeddinggemma`, with similarity indexing deferred to Phase 4.
- `ANTHROPIC_AUTH_TOKEN=ollama` matches Ollama's compatibility documentation, while `ANTHROPIC_API_KEY` is still accepted as a fallback alias in config.

### Next

- Keep Phase 2 and later integrations pointed at Ollama directly, using its Anthropic-compatible API for chat and native endpoints for embeddings.

## 2026-03-17 02:05

### Completed

- Implemented Phase 2 document upload, list, and detail endpoints.
- Added typed document response schemas and a document service layer for upload validation, checksum deduplication, and detail/list queries.
- Stored uploads on disk using checksum-based filenames while preserving original filenames in the database.
- Added API tests covering PDF validation, duplicate upload idempotency, list ordering, detail responses, and missing-document handling.

### Files Changed

- README.md
- app/api/__init__.py
- app/api/routes_documents.py
- app/db/schemas.py
- app/services/document_service.py
- tests/
- AGENTS_LOG.md

### Notes

- Duplicate uploads return the existing document with HTTP 200 and do not create additional files or rows.
- `page_count` remains `null`, `chunk_count` remains `0`, and `latest_ingestion` remains `null` until later phases add parsing and ingestion.

### Next

- Implement Phase 3 parsing, chunking, and the real ingestion endpoint.

## 2026-03-17 03:00

### Completed

- Implemented the asynchronous ingestion endpoint with persistent `ingestion_jobs` tracking and document status transitions.
- Added Docling-based parsing, normalized parsed JSON artifacts, deterministic chunking, and chunk replacement on re-ingest.
- Kept embeddings unset in Phase 3 while storing parsed chunk metadata in `document_chunks`.
- Added unit and integration tests for chunking, ingest success, re-ingest replacement, conflict handling, missing source files, and parser failure paths.

### Files Changed

- README.md
- scripts/ingest_sample.py
- app/api/routes_documents.py
- app/services/document_service.py
- app/ingestion/
- tests/
- AGENTS_LOG.md

### Notes

- `POST /documents/{document_id}/ingest` returns `202` immediately with a pending job, while `GET /documents/{document_id}` is the polling surface.
- Parsed artifacts are stored as normalized JSON in `PARSED_DIR/<document_id>.json`.
- Re-ingesting a document replaces prior chunks instead of appending duplicates.

### Next

- Implement Phase 4 embeddings, vector storage, and retrieval.
