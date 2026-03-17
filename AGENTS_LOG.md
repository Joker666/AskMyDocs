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

## 2026-03-17 03:08

### Completed

- Audited the dependency versions declared in `pyproject.toml` against current PyPI releases.
- Updated build, runtime, and dev dependency lower bounds to the latest stable versions currently published.
- Verified that `docling` is currently published on PyPI as `2.78.0`; there was no `2.80.0` release visible on PyPI at the time of the update.

### Files Changed

- pyproject.toml
- AGENTS_LOG.md

### Notes

- The dependency spec style remains lower-bounded (`>=...`) rather than exact pins, matching the existing project convention.
- This change updates declared minimums only; it does not install or lock packages in the workspace.

### Next

- Refresh the environment or lockfile if you want the local installation to match these newer minimums immediately.

## 2026-03-17 03:15

### Completed

- Corrected the dependency set to a resolvable combination by updating `docling` to `>=2.80.0` and constraining `pydantic-ai` to `>=1.61.0,<1.67.0`.
- Refreshed `uv.lock` and synced the local development environment to the updated dependency declarations.
- Verified `python -m compileall app tests scripts`, `uv run --locked ruff check .`, and `uv run --locked pyright` all pass.

### Files Changed

- pyproject.toml
- uv.lock
- AGENTS_LOG.md

### Notes

- The earlier `pydantic-ai>=1.67.0` bump conflicted with `docling` through incompatible `huggingface-hub` requirements.
- The lock refresh also corrected the earlier assumption that `docling 2.80.0` was unavailable; it resolved successfully during this validation pass.

### Next

- Continue Phase 4 work against the refreshed lockfile and dependency bounds.

## 2026-03-17 10:57

### Completed

- Fixed the ingestion pipeline to capture document metadata before the SQLModel session is closed, preventing detached-instance failures in background ingestion.
- Flushed chunk deletions before inserting replacement chunks during re-ingestion so the `(document_id, chunk_index)` uniqueness constraint is not violated.
- Verified the ingestion flow with `uv run pytest tests/test_ingestion.py`.

### Files Changed

- app/ingestion/pipeline.py
- AGENTS_LOG.md

### Notes

- The detached-instance error was triggered by reading `document.filename` and `document.file_path` after the session commit/close boundary in `run_ingestion_job`.
- Re-ingesting the same document exposed a second bug where old and new chunks shared chunk indexes inside one transaction.

### Next

- Continue Phase 4 work on embeddings and retrieval, with the ingestion pipeline now stable for repeated runs.

## 2026-03-17 11:20

### Completed

- Implemented the Ollama native embedding client with batch embedding, response validation, and model availability checks.
- Extended ingestion to generate and persist embeddings, while preserving the last good indexed chunks if a re-ingest embedding step fails.
- Added exact cosine retrieval helpers over pgvector and wired the native Ollama probe into `/health`.
- Added deterministic retrieval and embedding-failure tests, plus an optional live Ollama integration probe.
- Verified `uv run pytest`, `uv run ruff check .`, and `uv run pyright` all pass.

### Files Changed

- README.md
- app/api/routes_health.py
- app/db/vector_store.py
- app/ingestion/embedder.py
- app/ingestion/pipeline.py
- app/retrieval/search.py
- tests/test_config.py
- tests/test_health.py
- tests/test_ingestion.py
- tests/test_retrieval.py
- AGENTS_LOG.md

### Notes

- `/health` now actively checks Ollama native availability for the configured embedding model, while `anthropic_compat` remains deferred.
- Retrieval is exact cosine search only in Phase 4; ANN indexing and public query endpoints are still deferred.
- The live Ollama embedding test skips cleanly when Ollama is not running or the model is unavailable.

### Next

- Start Phase 5 by defining the typed agent output schema and wiring retrieval into the Pydantic AI query flow.

## 2026-03-17 11:53

### Completed

- Implemented the Phase 5 Pydantic AI query path with typed `Citation` and `AnswerResult` models, retrieval tools, citation validation, and the `/query` endpoint.
- Wired Ollama's Anthropic-compatible API into the answering agent and activated the `anthropic_compat` health check.
- Added query route/service tests, agent schema tests, tool-flow coverage with `FunctionModel`, and an optional live query integration test.
- Verified `uv run pytest`, `./.venv/bin/ruff check .`, and `uv run pyright` all pass.

### Files Changed

- README.md
- app/agent/
- app/api/__init__.py
- app/api/routes_health.py
- app/api/routes_query.py
- app/db/schemas.py
- app/dependencies.py
- app/services/query_service.py
- tests/test_agent_schema.py
- tests/test_health.py
- tests/test_query.py
- AGENTS_LOG.md

### Notes

- `/query` validates requested document IDs strictly: missing documents return `404`, and non-ready documents return `409`.
- The service performs retrieval before invoking the chat model and skips the model entirely when retrieval returns no hits.
- Final citations are enforced through a Pydantic AI output validator that only accepts fetched chunk context from the current run.

### Next

- Move into Phase 6 for broader polish, docs refinement, and any additional operational hardening.

## 2026-03-17 12:12

### Completed

- Added Phase 6 structured logging with stable event names and key/value output formatting.
- Centralized short safe runtime error sanitization and applied it across health checks, query failures, Docling parsing, Ollama embedding calls, and ingestion failure handling.
- Hardened query and ingestion entrypoints so dependency failures return sanitized `5xx` responses instead of leaking raw exception content.

### Files Changed

- app/logging.py
- app/runtime.py
- app/api/routes_health.py
- app/api/routes_documents.py
- app/api/routes_query.py
- app/services/document_service.py
- app/services/query_service.py
- app/agent/agent.py
- app/agent/tools.py
- app/ingestion/parser.py
- app/ingestion/embedder.py
- app/ingestion/pipeline.py
- app/retrieval/search.py

### Notes

- Log payloads now avoid full document text and full user questions, using counts and lengths instead.
- Ingestion failures preserve the last good ready index when re-ingest embedding work fails, while still recording a failed job.

### Next

- Finish the Phase 6 operator scripts, refresh README instructions, and add targeted observability/failure tests.

## 2026-03-17 12:14

### Completed

- Expanded the local operator scripts for Phase 6.
- Added optional end-to-end query support and non-zero failure exits to `scripts/ingest_sample.py`.
- Implemented `scripts/reset_db.py` with explicit confirmation and optional artifact deletion.
- Improved `scripts/bootstrap.sh` prerequisite checks and operator guidance.
- Rewrote the README to document bootstrap, health, upload, ingest, query, reset, and troubleshooting flows.

### Files Changed

- scripts/bootstrap.sh
- scripts/ingest_sample.py
- scripts/reset_db.py
- README.md

### Notes

- The reset script truncates app tables without altering migration state.
- The ingest sample script remains suitable for local demos because it polls the existing REST API instead of importing app internals.

### Next

- Add targeted Phase 6 tests for sanitized failures, log events, and script behavior, then run the full verification suite.

## 2026-03-17 12:18

### Completed

- Added Phase 6 regression coverage for sanitized health/query/ingestion failures, structured log events, and helper script behavior.
- Verified the final Phase 6 implementation with `uv run pytest`, `uv run ruff check .`, and `uv run pyright`.

### Files Changed

- tests/test_health.py
- tests/test_ingestion.py
- tests/test_query.py
- tests/test_scripts.py
- AGENTS_LOG.md

### Notes

- Verification is green with 55 passing tests.
- The remaining test output warnings come from upstream `docling` and `pydantic_ai` deprecations rather than project code failures.

### Next

- Phase 6 is complete; the next major work should start only if you want to move beyond the MVP scope.

## 2026-03-17 12:56

### Completed

- Added Langfuse v4 tracing across FastAPI requests, document upload/ingestion, embedding, retrieval, query orchestration, and Pydantic AI agent/tool execution.
- Introduced a shared observability module for Langfuse client lifecycle, Pydantic AI OpenTelemetry instrumentation, request attribute propagation, and safe trace payload shaping.
- Documented Langfuse environment setup and the default trace data policy in the README and `.env.example`.

### Files Changed

- pyproject.toml
- uv.lock
- .env.example
- README.md
- app/config.py
- app/main.py
- app/observability.py
- app/agent/agent.py
- app/agent/tools.py
- app/services/document_service.py
- app/services/query_service.py
- app/retrieval/search.py
- app/ingestion/embedder.py
- app/ingestion/pipeline.py
- tests/test_ingestion.py
- AGENTS_LOG.md

### Notes

- Langfuse tracing is enabled only when credentials are configured; Pydantic AI content capture is intentionally disabled so raw prompts and retrieved document text are not exported by default.
- `pytest` runs skip Langfuse initialization to avoid noisy exporter failures and test-trace pollution.

### Next

- If you want richer trace detail later, the main decision is whether to selectively allow prompt/tool content for trusted environments or keep the current metadata-only policy.

## 2026-03-17 13:03

### Completed

- Switched Langfuse tracing from metadata-only to content-rich capture.
- Enabled Pydantic AI content instrumentation so prompts, completions, retrieved chunk text, and tool payload bodies are exported to Langfuse.
- Removed the Langfuse masking rules that were redacting text-bearing span fields, while still masking raw uploaded bytes.

### Files Changed

- app/observability.py
- README.md
- AGENTS_LOG.md

### Notes

- Manual service spans still keep short previews for some top-level query fields, but agent/tool spans now contain the full payloads needed for debugging retrieval and grounding.

### Next

- If you later want to narrow this again, add an explicit config gate around `include_content` and the masking policy.

## 2026-03-17 13:33

### Completed

- Implemented `app/retrieval/context_builder.py` to expand selected hits into a local same-document chunk window.
- Wired `fetch_chunk_context` to return adjacent chunks around retrieved hits instead of only the exact matched chunks.
- Added unit coverage for context-window expansion, overlap deduplication, and document-boundary isolation.

### Files Changed

- app/retrieval/context_builder.py
- app/agent/tools.py
- tests/test_context_builder.py
- AGENTS_LOG.md

### Notes

- The first pass uses a simple `[-1, +1]` chunk window per selected hit and preserves stable local ordering.
- This improves local context assembly after retrieval, but it does not yet change vector ranking, increase retrieval recall, or add reranking.

### Next

- The next retrieval improvement should be higher internal recall before answer generation, then reranking over the larger candidate set.

## 2026-03-17 14:01

### Completed

- Integrated Logfire log shipping into the existing stdlib logging bootstrap using the official `LogfireLoggingHandler`.
- Added typed Logfire settings so export is controlled explicitly by `LOGFIRE_TOKEN` and related env vars.
- Documented the new Logfire configuration and added focused config/logging tests.

### Files Changed

- app/config.py
- app/logging.py
- app/main.py
- .env.example
- README.md
- tests/test_config.py
- tests/test_logging.py
- AGENTS_LOG.md

### Notes

- Console logging still uses the existing key/value formatter on stdout.
- Logfire export is only enabled when `LOGFIRE_TOKEN` is set, which avoids accidental use of local Logfire credentials during tests or unconfigured runs.

### Next

- Set `LOGFIRE_TOKEN` in the runtime environment and verify new app logs appear in the target Logfire project dashboard.
