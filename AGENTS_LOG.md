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
