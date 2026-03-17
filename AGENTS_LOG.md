## 2026-03-17 12:12

### Completed

- Condensed the original build transcript into a single historical summary now that the MVP is complete.
- Completed the end-to-end AskMyDocs MVP: project bootstrap, database and migrations, health checks, document upload and storage, ingestion jobs, Docling parsing, chunking, Ollama embeddings, pgvector retrieval, Pydantic AI query flow, structured logging, scripts, and test coverage.
- Stabilized ingestion and re-ingestion behavior, added Ollama connectivity checks, and hardened runtime error handling.

### Files Changed

- app/
- tests/
- scripts/
- migrations/
- README.md
- pyproject.toml
- uv.lock
- docker-compose.yml
- .env.example
- AGENTS.md
- AGENTS_LOG.md

### Notes

- This entry replaces the earlier phase-by-phase log with a shorter project-level summary.
- The current baseline is a working local MVP with document-grounded answers and citation validation.

### Next

- Record only meaningful completed changes going forward, and keep future log entries grouped and concise.

## 2026-03-17 14:37

### Completed

- Rewrote `AGENTS.md` so it no longer instructs agents to work in build phases.
- Shifted the instructions from MVP construction to maintenance and incremental extension of the completed app.
- Added guidance to keep `AGENTS_LOG.md` concise and to compress older history when the log grows too long.
- Replaced the verbose historical log with a compressed summary entry plus this documentation update entry.

### Files Changed

- AGENTS.md
- AGENTS_LOG.md

### Notes

- The project instructions now describe the current baseline rather than a future implementation plan.
- The logging policy now favors one entry per meaningful completed change instead of detailed per-phase narration.

### Next

- Keep future instruction updates aligned with the shipped behavior and avoid reintroducing phased build guidance unless the project is intentionally reset.

## 2026-03-17 14:51

### Completed

- Added a `/query` lifecycle diagram to the README showing preflight retrieval, model tool calls, context expansion, and output validation.
- Documented the context-engineering implementation directly in `app/retrieval/context_builder.py` with detailed function docstrings.

### Files Changed

- README.md
- app/retrieval/context_builder.py
- AGENTS_LOG.md

### Notes

- The README now makes it explicit that retrieval can short-circuit before the model runs and that the model chooses among registered tools during the agent run.
- The code comments describe the current context strategy as same-document adjacency expansion around retrieved hits.

### Next

- Keep README and inline code documentation aligned if the retrieval pipeline or context-window behavior changes.

## 2026-03-17 18:38

### Completed

- Relaxed quote validation in `validate_answer_result` to use fuzzy matching (`SequenceMatcher` ≥ 0.7) instead of exact substring containment.
- Added `_backfill_citation_metadata` to auto-populate `document_id`, `filename`, `page_number`, and `section_title` from fetched chunks, removing four metadata-mismatch failure modes.
- Allowed empty-citation answers when `confidence` is 0.0, enabling graceful "not found" responses without triggering retries.

### Files Changed

- app/agent/agent.py

### Notes

- The previous strict validation caused frequent "Exceeded maximum retries" errors because the LLM would paraphrase quotes or slightly alter metadata fields.
- The model now only needs to get `chunk_id` and an approximate `quote` right; metadata is corrected automatically.

### Next

- Consider improving the system prompt with explicit tool-calling and formatting instructions if validation failures persist.

## 2026-03-17 18:54

### Completed

- Expanded `QUERY_SYSTEM_PROMPT` with explicit instructions to call `fetch_chunk_context` before answering, copy quotes verbatim, and clarify the zero-confidence path.
- Added `_preseed_deps` in `query_service.py` to pre-populate `search_results_by_id` and `fetched_chunks_by_id` from pre-flight retrieval results before running the agent.
- Renamed `_load_chunk_context` → `load_chunk_context` in `tools.py` to make it importable by `query_service.py`.

### Files Changed

- app/agent/prompts.py
- app/agent/tools.py
- app/services/query_service.py

### Notes

- Pre-seeding means the output validator has chunk data available even if the model skips tool calls. If the model does call the tools, they overwrite the pre-seeded data.
- The prompt now makes the required workflow (search → fetch → answer) and quote rules explicitly clear.

### Next

- Monitor whether validation failures persist with these combined changes.
