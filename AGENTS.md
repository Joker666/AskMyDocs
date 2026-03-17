# AGENTS.md

## Project

AskMyDocs

Local document Q&A assistant over PDFs using:

- FastAPI
- Docling
- PostgreSQL + pgvector
- Pydantic AI
- Ollama

The system ingests local PDF documents, extracts structured text, chunks and embeds them, stores vectors in Postgres, and answers user questions with grounded citations using Ollama's Anthropic-compatible API for chat and Ollama's native API for embeddings.

---

## Goal

Build a small but clean MVP that demonstrates:

1. PDF ingestion
2. structured document parsing
3. embedding + vector retrieval
4. agent tool calling
5. typed, validated final answers
6. citation-aware responses

This project should be easy to run locally and easy to extend later.

---

## Product Scope

### Core user flow

1. User uploads one or more PDF files
2. Backend parses PDFs with Docling
3. Parsed content is chunked and embedded
4. Chunks and embeddings are stored in PostgreSQL with pgvector
5. User asks a question
6. Pydantic AI agent decides which retrieval tools to call
7. Retrieved context is passed to the chat model through Ollama's Anthropic-compatible API
8. API returns:
   - answer
   - supporting citations
   - chunk references embedded in each citation object (`chunk_id`, document metadata, and quote)

---

## Non-Goals for MVP

Do not build these yet unless the core path is complete:

- authentication
- multi-user tenancy
- frontend SPA
- streaming tokens
- reranking model
- OCR fallback pipeline
- hybrid BM25 + vector search
- document deletion UI
- conversation memory
- table extraction optimization
- distributed workers

---

## Tech Stack

### Backend

- Python 3.13+
- FastAPI
- Uvicorn
- Pydantic v2
- Pydantic AI

### Document Processing

- Docling

### Storage

- PostgreSQL
- pgvector
- SQLModel

### LLM + Embeddings

- Ollama
- Ollama Anthropic-compatible API for chat and tool-calling
- Suggested chat model exposed by Ollama: `kimi-k2.5:cloud`
- Suggested embedding model in Ollama: `embeddinggemma`

### Dev Tooling

- uv (global). Use alias `pipi`. For example `pipi "fastapi[standard]"` should install `fastapi[standard]`.
- pytest
- ruff
- pyright

---

## High-Level Architecture

```text
Client
  ↓
FastAPI
  ↓
Pydantic AI Agent
  ├── search_chunks(query, top_k)
  ├── fetch_chunk_context(chunk_ids)
  └── list_documents()
  ↓
Postgres + pgvector
  ↑
Embedding pipeline
  ↑
Docling PDF parser
  ↑
Uploaded PDF files
```

---

## Directory Structure

Use this exact structure unless there is a strong reason to change it.

```text
askmydocs/
├── AGENTS.md
├── AGENTS_LOG.md
├── README.md
├── pyproject.toml
├── .env.example
├── docker-compose.yml
├── migrations/
├── data/
│   ├── uploads/
│   └── parsed/
├── scripts/
│   ├── bootstrap.sh
│   ├── ingest_sample.py
│   └── reset_db.py
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── logging.py
│   ├── dependencies.py
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes_health.py
│   │   ├── routes_documents.py
│   │   └── routes_query.py
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── models.py
│   │   ├── agent.py
│   │   ├── prompts.py
│   │   └── tools.py
│   ├── db/
│   │   ├── __init__.py
│   │   ├── session.py
│   │   ├── models.py
│   │   ├── schemas.py
│   │   └── vector_store.py
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── parser.py
│   │   ├── chunker.py
│   │   ├── embedder.py
│   │   └── pipeline.py
│   ├── retrieval/
│   │   ├── __init__.py
│   │   ├── search.py
│   │   └── context_builder.py
│   └── services/
│       ├── __init__.py
│       ├── document_service.py
│       └── query_service.py
└── tests/
    ├── test_health.py
    ├── test_chunker.py
    ├── test_ingestion.py
    ├── test_retrieval.py
    └── test_agent_schema.py
```

---

## Data Model

Implement these database tables.

### documents

Stores one row per uploaded file.

Fields:

- id
- filename
- file_path
- checksum
- page_count
- status
- created_at
- updated_at

Recommended `documents.status` values for MVP:

- `uploaded`
- `ingesting`
- `ready`
- `failed`

### document_chunks

Stores parsed text chunks.

Fields:

- id
- document_id
- chunk_index
- page_number
- section_title
- text
- token_estimate
- metadata_json
- embedding vector

### ingestion_jobs

Required for MVP.

Use `FastAPI BackgroundTasks` and persistent job state.

Fields:

- id
- document_id
- status
- error_message
- started_at
- completed_at

Recommended `ingestion_jobs.status` values for MVP:

- `pending`
- `running`
- `completed`
- `failed`

---

## Pydantic Models

Create these first.

### Agent output schema

```python
class Citation(BaseModel):
    document_id: int
    chunk_id: int
    filename: str
    page_number: int | None
    section_title: str | None
    quote: str

class AnswerResult(BaseModel):
    answer: str
    citations: list[Citation]
    confidence: float
```

Rules:

- `confidence` is a bounded float from 0.0 to 1.0
- citations must always refer to real retrieved chunks
- quote should be short and directly relevant

### API schemas

Create:

- `DocumentUploadResponse`
- `DocumentListResponse`
- `DocumentDetailResponse`
- `IngestionStatusResponse`
- `QueryRequest`
- `QueryResponse`

Use these exact payload shapes for MVP:

```python
class DocumentSummary(BaseModel):
    id: int
    filename: str
    page_count: int | None
    status: str
    created_at: datetime
    updated_at: datetime

class DocumentUploadResponse(BaseModel):
    document: DocumentSummary

class DocumentListResponse(BaseModel):
    documents: list[DocumentSummary]

class IngestionStatusResponse(BaseModel):
    job_id: int
    document_id: int
    status: str
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    chunk_count: int

class DocumentDetailResponse(BaseModel):
    id: int
    filename: str
    file_path: str
    checksum: str
    page_count: int | None
    status: str
    chunk_count: int
    created_at: datetime
    updated_at: datetime
    latest_ingestion: IngestionStatusResponse | None

class QueryRequest(BaseModel):
    question: str
    document_ids: list[int] | None = None
    top_k: int = Field(default=5, ge=1, le=20)

class QueryResponse(BaseModel):
    answer: str
    citations: list[Citation]
    confidence: float
```

---

## Required Endpoints

### Health

- `GET /health`

Returns:

- app status
- db connectivity
- Anthropic-compatible Ollama connectivity
- Ollama native API connectivity

### Documents

- `POST /documents/upload`
- `GET /documents`
- `GET /documents/{document_id}`
- `POST /documents/{document_id}/ingest`

For MVP, `POST /documents/upload` accepts a single PDF file per request. Uploading multiple files is supported by making repeated calls.

Response contracts:

- `POST /documents/upload` returns `DocumentUploadResponse`
- `GET /documents` returns `DocumentListResponse`
- `GET /documents/{document_id}` returns `DocumentDetailResponse`
- `POST /documents/{document_id}/ingest` returns `IngestionStatusResponse`

### Query

- `POST /query`

Example request:

```json
{
  "question": "What loss terms are described in this document?",
  "document_ids": [1, 2],
  "top_k": 5
}
```

Example response:

```json
{
  "answer": "The document describes ...",
  "citations": [
    {
      "document_id": 1,
      "chunk_id": 14,
      "filename": "thesis.pdf",
      "page_number": 22,
      "section_title": "Methodology",
      "quote": "The total loss combines forecasting error with ..."
    }
  ],
  "confidence": 0.83
}
```

`POST /query` returns `QueryResponse`. `citations` are the only chunk references returned by the API for MVP.

---

## Tooling Contract for the Agent

The agent must use tool calling through Pydantic AI.

Implement these tools.

### 1. `list_documents()`

Returns available documents and IDs.

Use when:

- user asks what documents are available
- user does not specify a document and the agent needs context

### 2. `search_chunks(query: str, document_ids: list[int] | None, top_k: int = 5)`

Runs embedding search against pgvector.

Returns:

- chunk ID
- document ID
- filename
- page number
- section title
- text excerpt
- similarity score

### 3. `fetch_chunk_context(chunk_ids: list[int])`

Returns richer chunk text for a selected set of chunk IDs.

Each returned item must include:

- chunk ID
- document ID
- filename
- page number
- section title
- full chunk text

Use when:

- the agent has identified relevant chunk IDs and needs exact context before answering

### 4. `get_document_metadata(document_id: int)`

Returns:

- filename
- page count
- status
- chunk count

---

## Agent Behavior Rules

The answering agent must follow these rules:

1. Never answer from prior knowledge when the answer should come from uploaded documents.
2. Prefer calling `search_chunks` before answering.
3. Use `fetch_chunk_context` before composing the final answer if search results are short.
4. Only cite retrieved chunks.
5. If evidence is weak, say so.
6. Do not fabricate page numbers, section titles, or quotes.
7. If nothing relevant is found, return a graceful failure message, empty citations, and `confidence=0.0`.
8. Final output must always validate against `AnswerResult`.

---

## Prompting Rules

System prompt should make these constraints explicit:

- You are a document-grounded assistant.
- Answer only from retrieved document context.
- Use tools when needed.
- Keep answers concise but useful.
- Cite supporting passages.
- If the answer is not in the documents, say that clearly.
- Do not invent citations.

---

## Ingestion Pipeline

Build the ingestion flow in this order.

### Step 1. Save uploaded file

- store original file under `data/uploads/`
- compute checksum
- create document row
- create an `ingestion_jobs` row with status `pending` before starting parse work

### Step 2. Parse with Docling

- extract text and page-level structure
- preserve page numbers where possible
- preserve section headings if available

### Step 3. Chunk the content

Chunking rules:

- target chunk size: 500 to 900 characters
- chunk overlap: 100 to 150 characters
- do not merge across page boundaries unless clearly beneficial
- attach metadata:
  - page number
  - section title
  - source filename
  - chunk index

### Step 4. Generate embeddings with Ollama

- embed each chunk
- fail clearly if embedding model is unavailable

### Step 5. Store in pgvector

- insert chunk rows with embeddings
- update document and ingestion job status

---

## Retrieval Rules

Implement cosine similarity search first.

MVP retrieval plan:

1. embed user query
2. filter by optional document IDs
3. retrieve top-k nearest chunks
4. return chunk metadata and similarity scores

Do not implement reranking yet.

---

## Environment Variables

Create `.env.example` with these keys:

```env
APP_ENV=development
APP_HOST=0.0.0.0
APP_PORT=8000

POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=askmydocs
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres

ANTHROPIC_BASE_URL=http://localhost:11434
ANTHROPIC_AUTH_TOKEN=ollama
ANTHROPIC_MODEL_NAME=kimi-k2.5:cloud

OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_EMBED_MODEL=embeddinggemma
EMBEDDING_DIMENSION=768

UPLOAD_DIR=./data/uploads
PARSED_DIR=./data/parsed
LOG_LEVEL=INFO
```

Notes:

- Use `ANTHROPIC_BASE_URL` for Ollama's Anthropic-compatible chat and tool-calling path.
- Use `OLLAMA_BASE_URL` for Ollama native endpoints such as embeddings.
- Both URLs may point to the same Ollama host in local development.

---

## Docker Compose

Provide a `docker-compose.yml` for local development with:

- postgres
- pgvector-enabled image

Do not containerize Ollama for MVP unless it is trivial and stable on the target machine. Assume Ollama runs locally on the host.

---

## Development Phases

Complete work in phases. Update `AGENTS_LOG.md` after each phase.

### Phase 1: Project bootstrap

Tasks:

- initialize Python project
- add dependencies
- create app skeleton
- create docker-compose for Postgres
- set up DB session and models
- add health endpoint

Acceptance criteria:

- app starts
- `/health` returns success
- DB connection works

### Phase 2: Document upload and storage

Tasks:

- implement upload endpoint
- save files to disk
- create document row
- implement list documents endpoint

Acceptance criteria:

- PDF upload works
- document appears in DB
- file is present on disk

### Phase 3: Parsing and chunking

Tasks:

- integrate Docling parser
- build chunker
- preserve metadata
- add ingestion endpoint

Acceptance criteria:

- uploaded PDF can be parsed
- chunks are created with metadata
- ingestion status is visible
- `ingestion_jobs` is populated and updated correctly

### Phase 4: Embeddings and pgvector retrieval

Tasks:

- add Ollama embedding client
- store vectors in pgvector
- implement similarity search
- write retrieval tests

Acceptance criteria:

- chunks are embedded and stored
- query embedding search returns relevant chunks

### Phase 5: Pydantic AI agent

Tasks:

- define answer schema
- create tools
- wire Pydantic AI to Ollama's Anthropic-compatible API
- implement `/query`

Acceptance criteria:

- agent uses retrieval tools
- response validates against schema
- citations refer to real chunks

### Phase 6: Quality and polish

Tasks:

- add logging
- improve error handling
- add README
- add basic tests
- add bootstrap and sample ingestion scripts

Acceptance criteria:

- clean local setup
- clear README instructions
- passing tests

---

## Testing Strategy

Add tests for the following:

### Unit tests

- chunking behavior
- citation schema validation
- retrieval filtering by document ID

### Integration tests

- upload a sample PDF
- ingest it
- run a query
- verify citations are returned

### Contract tests

- `/query` response always matches API schema
- agent output always matches `AnswerResult`

---

## Error Handling Rules

Handle these cases cleanly:

- uploaded file is not a PDF
- Docling parsing fails
- embedding model unavailable in Ollama
- database is unavailable
- query returns no relevant chunks
- requested document ID does not exist

Responses should be informative but short. Do not leak stack traces to API consumers.

---

## Logging

Add structured logs for:

- upload started/completed
- ingestion started/completed/failed
- embedding batch progress
- query start/end
- tool calls made by the agent
- database and Ollama connectivity failures

---

## Performance Constraints for MVP

Keep it simple and safe:

- synchronous ingestion is acceptable for first pass
- document size target: small to medium PDFs
- avoid premature optimization
- prefer readable code over abstraction-heavy design

---

## Code Quality Rules

1. Use type hints everywhere.
2. Prefer small, testable modules.
3. Keep business logic out of route handlers.
4. Use service layer functions for orchestration.
5. Avoid hidden globals.
6. Keep prompts in dedicated files.
7. Keep Ollama integration isolated behind a thin client wrapper.
8. Do not hardcode model names outside config.

---

## Implementation Notes

### FastAPI

- keep routes thin
- validate request bodies with Pydantic

### Docling

- isolate parser-specific logic in `app/ingestion/parser.py`
- normalize parser output into internal document structures

### pgvector

- create vector extension via migration
- require `EMBEDDING_DIMENSION` in config and use it consistently in the pgvector column definition and migrations
- do not auto-detect or mutate vector dimensions at runtime

### Pydantic AI

- use typed result model
- expose retrieval operations as explicit tools
- ensure the final answer is schema-validated
- configure the model client against Ollama's Anthropic-compatible API

### Ollama

- add health check helper
- separate chat client and embedding client
- use Ollama directly for embeddings
- treat the chat model as reachable through Ollama's Anthropic-compatible API
- fail fast if the required Ollama-compatible chat or embedding endpoints are unavailable

---

## Definition of Done

The MVP is done when all of the following are true:

- a PDF can be uploaded
- the PDF can be parsed and chunked
- chunks can be embedded and stored in pgvector
- a question can be asked through `/query`
- the agent uses tool calling to retrieve evidence
- the final answer is validated by Pydantic
- citations reference real stored chunks
- the project runs locally with documented setup steps

---

## Stretch Goals After MVP

Only start these after MVP is complete.

1. reranking
2. streaming answers
3. background ingestion jobs
4. frontend UI
5. hybrid search
6. document deletion and reindexing
7. chat history
8. answer highlighting by page
9. markdown and DOCX support
10. evaluation harness with golden questions

---

## Required `AGENTS_LOG.md` Format

After each meaningful step, append a dated log entry with:

- what was done
- files created/changed
- current status
- blockers
- next step

Use this template:

```md
## YYYY-MM-DD HH:MM

### Completed

- ...

### Files Changed

- ...

### Notes

- ...

### Next

- ...
```

---

## Final Instruction to the Agent

Build the smallest clean version that works end to end.

Priority order:

1. correctness
2. clarity
3. grounded retrieval
4. typed outputs
5. local reproducibility

Do not over-engineer the MVP.
