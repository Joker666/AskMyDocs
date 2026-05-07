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

## 2026-03-17 19:20

### Completed

- Added Exa API hybrid search support (Phases 1+2).
- Phase 1: Exa config fields in `config.py`, env vars in `.env.example`, `exa_py` dependency, `app/retrieval/exa_search.py` client wrapper with observability, Exa health check in `routes_health.py`.
- Phase 2: `app/retrieval/fusion.py` with weighted Reciprocal Rank Fusion (RRF), `hybrid_search()` orchestrator in `search.py` that transparently fuses pgvector + Exa results.

### Files Changed

- app/config.py
- app/retrieval/exa_search.py (new)
- app/retrieval/fusion.py (new)
- app/retrieval/search.py
- app/api/routes_health.py
- .env.example
- pyproject.toml
- tests/test_exa_search.py (new)
- tests/test_fusion.py (new)
- tests/test_health.py

### Notes

- Exa is disabled by default (`EXA_ENABLED=false`). When disabled, `hybrid_search()` returns wrapped local-only results.
- Exa failures are handled gracefully — if the API is unreachable, the system falls back to local results silently.
- Circular import between `fusion.py` and `search.py` resolved with `TYPE_CHECKING` guard.

### Next

- Phase 3: Wire `hybrid_search()` into agent tools, add `WebCitation` model and `web_citations` response field.
- Phase 4: Observability spans, cost tracking, documentation.

## 2026-03-17 19:44

### Completed

- Phase 3: Wired hybrid search into the agent tools (transparent fusion).
- Added `WebCitation` model and `web_citations` field to `AnswerResult` and `QueryResponse` (backward compatible, defaults to empty list).
- Updated `search_chunks` tool to call `hybrid_search()` and map `FusedResult` into `SearchChunkResult` with `source`/`url`/`title` fields.
- Updated system prompt with web result handling rules.
- Updated `query_service.py` to pass `web_citations` through to the API response.

### Files Changed

- app/agent/models.py
- app/agent/tools.py
- app/agent/prompts.py
- app/db/schemas.py
- app/services/query_service.py
- tests/test_query.py

### Notes

- The `Citation` model is unchanged; web citations live in a separate `web_citations` field.
- The agent is instructed to prefer document citations and use web results only as supplementary context.

### Next

- Phase 4: Observability spans for Exa calls, cost tracking, documentation.

## 2026-03-18 13:58

### Completed

- Phase 4: Added observability, cost tracking, and documentation for hybrid search.
- `hybrid_search()` now emits a Langfuse `retrieval.hybrid_search` span with mode, result counts, and Exa cost estimate.
- Added `_estimate_exa_cost()` based on Exa pricing: ~$0.017 per query with 5 results.
- Structured logs for every fusion path: `local_only`, `local_only_exa_failed`, `local_only_exa_empty`, `fused`.
- Updated README with Hybrid Search (Exa) section: how it works, configuration, cost, and updated response shape.

### Files Changed

- app/retrieval/search.py
- README.md
- AGENTS_LOG.md

### Notes

- All four hybrid search phases are now complete.
- Exa remains disabled by default; no breaking changes to existing behavior.

## 2026-05-07 02:02

### Completed

- Added `_validate_web_citation` to output validator: checks URL exists in `deps.web_results`, enforces quote length limit.
- Changed `exa_search_type` from `str` to `Literal["auto", "neural", "keyword"]` in config to catch invalid values at startup.
- Updated confidence check to consider `web_citations` as valid citations (not just `citations`).
- Documented the pre-flight retrieval design decision (local-only, not hybrid) in README.

### Files Changed

- app/agent/agent.py
- app/config.py
- README.md
