from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any, cast

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel
from sqlmodel import Session, delete, select

from app.agent.agent import build_query_agent, check_anthropic_compat
from app.agent.models import AnswerResult, Citation
from app.agent.tools import QueryAgentDeps
from app.config import Settings
from app.db.models import Document, DocumentChunk, IngestionJob
from app.db.schemas import QueryRequest
from app.db.session import get_engine
from app.dependencies import get_app_settings, get_db_session
from app.ingestion.embedder import OllamaNativeError
from app.main import app
from app.retrieval.search import SearchResult
from app.services.query_service import QueryAgentError, run_query_agent


def make_settings(upload_dir: Path, parsed_dir: Path) -> Settings:
    settings_cls = cast(Any, Settings)
    return settings_cls(
        POSTGRES_HOST="localhost",
        POSTGRES_DB="askmydocs",
        POSTGRES_USER="postgres",
        POSTGRES_PASSWORD=SecretStr("postgres"),
        UPLOAD_DIR=str(upload_dir),
        PARSED_DIR=str(parsed_dir),
    )


@pytest.fixture
def query_test_environment(tmp_path):
    settings = make_settings(tmp_path / "uploads", tmp_path / "parsed")
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.parsed_dir).mkdir(parents=True, exist_ok=True)

    try:
        with psycopg.connect(settings.migration_database_url):
            pass
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres not available for query tests: {exc}")

    engine = get_engine(settings)
    with Session(engine) as session:
        session.exec(delete(IngestionJob))
        session.exec(delete(DocumentChunk))
        session.exec(delete(Document))
        session.commit()

    def override_settings() -> Settings:
        return settings

    def override_db_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_app_settings] = override_settings
    app.dependency_overrides[get_db_session] = override_db_session
    client = TestClient(app)

    yield client, settings, engine

    app.dependency_overrides.clear()
    with Session(engine) as session:
        session.exec(delete(IngestionJob))
        session.exec(delete(DocumentChunk))
        session.exec(delete(Document))
        session.commit()


def build_pdf(pages: list[list[str]]) -> bytes:
    objects: list[bytes] = []

    def add_object(payload: bytes) -> int:
        objects.append(payload)
        return len(objects)

    font_id = add_object(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    page_ids: list[int] = []

    for page_lines in pages:
        stream_lines = [b"BT", b"/F1 14 Tf", b"72 720 Td"]
        first_line = True
        for line in page_lines:
            escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            if not first_line:
                stream_lines.append(b"0 -22 Td")
            stream_lines.append(f"({escaped}) Tj".encode())
            first_line = False
        stream_lines.append(b"ET")
        stream = b"\n".join(stream_lines)
        content_id = add_object(b"<< /Length %d >>\nstream\n%b\nendstream" % (len(stream), stream))
        page_id = add_object(
            b"<< /Type /Page /Parent 0 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>"
            % (font_id, content_id)
        )
        page_ids.append(page_id)

    kids_refs = b" ".join(f"{page_id} 0 R".encode() for page_id in page_ids)
    pages_id = add_object(b"<< /Type /Pages /Count %d /Kids [ %b ] >>" % (len(page_ids), kids_refs))
    catalog_id = add_object(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id)

    for page_id in page_ids:
        objects[page_id - 1] = objects[page_id - 1].replace(
            b"/Parent 0 0 R", b"/Parent %d 0 R" % pages_id
        )

    pdf = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{index} 0 obj\n".encode())
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")

    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode())
    pdf.extend(
        b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
        % (len(objects) + 1, catalog_id, xref_offset)
    )
    return bytes(pdf)


def ingestable_pdf_bytes() -> bytes:
    page_one = [
        "Phase 5 Query Title",
        "This document explains the query pipeline and the answer must stay grounded.",
    ]
    page_two = [
        "Supporting Details",
        "The agent should cite fetched chunk context and avoid fabricating metadata.",
    ]
    return build_pdf([page_one, page_two])


def _embedding_for_text(text: str, dimension: int) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return [digest[index % len(digest)] / 255.0 for index in range(dimension)]


@pytest.fixture(autouse=True)
def stub_pipeline_embeddings(monkeypatch):
    def fake_embed_texts(texts: list[str], settings: Settings) -> list[list[float]]:
        return [_embedding_for_text(text, settings.embedding_dimension) for text in texts]

    monkeypatch.setattr("app.ingestion.pipeline.embed_texts", fake_embed_texts)


def _upload_and_ingest(client: TestClient) -> int:
    upload = client.post(
        "/documents/upload",
        files={"file": ("query.pdf", ingestable_pdf_bytes(), "application/pdf")},
    )
    document_id = upload.json()["document"]["id"]
    ingest = client.post(f"/documents/{document_id}/ingest")
    assert ingest.status_code == 202
    return document_id


def _get_first_chunk(engine, document_id: int) -> DocumentChunk:
    with Session(engine) as session:
        chunk = session.exec(
            select(DocumentChunk).where(DocumentChunk.document_id == document_id)
        ).first()
        assert chunk is not None
        assert chunk.id is not None
        return chunk


def _search_result_from_chunk(chunk: DocumentChunk, document_id: int) -> SearchResult:
    return SearchResult(
        chunk_id=cast(int, chunk.id),
        document_id=document_id,
        filename="query.pdf",
        page_number=chunk.page_number,
        section_title=chunk.section_title,
        text=chunk.text,
        similarity_score=0.91,
    )


def test_query_route_returns_expected_shape(query_test_environment, monkeypatch) -> None:
    client, _, engine = query_test_environment
    document_id = _upload_and_ingest(client)
    chunk = _get_first_chunk(engine, document_id)

    def fake_search_chunks(**_kwargs) -> list[SearchResult]:
        return [_search_result_from_chunk(chunk, document_id)]

    def fake_run_query_agent(**_kwargs) -> AnswerResult:
        return AnswerResult(
            answer="The document says the answer must stay grounded.",
            citations=[
                Citation(
                    document_id=document_id,
                    chunk_id=cast(int, chunk.id),
                    filename="query.pdf",
                    page_number=chunk.page_number,
                    section_title=chunk.section_title,
                    quote="the answer must stay grounded",
                )
            ],
            confidence=0.82,
        )

    monkeypatch.setattr("app.services.query_service.search_chunks", fake_search_chunks)
    monkeypatch.setattr("app.services.query_service.run_query_agent", fake_run_query_agent)

    response = client.post(
        "/query",
        json={"question": "What should the answer do?", "document_ids": [document_id], "top_k": 5},
    )

    assert response.status_code == 200
    assert response.json() == {
        "answer": "The document says the answer must stay grounded.",
        "citations": [
            {
                "document_id": document_id,
                "chunk_id": cast(int, chunk.id),
                "filename": "query.pdf",
                "page_number": chunk.page_number,
                "section_title": chunk.section_title,
                "quote": "the answer must stay grounded",
            }
        ],
        "confidence": 0.82,
    }


def test_query_without_document_ids_uses_ready_documents_only(
    query_test_environment,
    monkeypatch,
) -> None:
    client, _, _ = query_test_environment
    ready_document_id = _upload_and_ingest(client)
    client.post(
        "/documents/upload",
        files={"file": ("uploaded-only.pdf", ingestable_pdf_bytes(), "application/pdf")},
    )

    def fake_search_chunks(**_kwargs) -> list[SearchResult]:
        return [SearchResult(
            chunk_id=1,
            document_id=ready_document_id,
            filename="query.pdf",
            page_number=1,
            section_title="Phase 5 Query Title",
            text="ready only",
            similarity_score=0.9,
        )]

    def fake_run_query_agent(**kwargs) -> AnswerResult:
        assert kwargs["document_ids"] == [ready_document_id]
        return AnswerResult(
            answer="Ready documents were used.",
            citations=[
                Citation(
                    document_id=ready_document_id,
                    chunk_id=1,
                    filename="query.pdf",
                    page_number=1,
                    section_title="Phase 5 Query Title",
                    quote="ready only",
                )
            ],
            confidence=0.7,
        )

    monkeypatch.setattr("app.services.query_service.search_chunks", fake_search_chunks)
    monkeypatch.setattr("app.services.query_service.run_query_agent", fake_run_query_agent)

    response = client.post("/query", json={"question": "Which documents are queryable?"})

    assert response.status_code == 200
    assert response.json()["answer"] == "Ready documents were used."


def test_query_missing_requested_document_returns_404(query_test_environment) -> None:
    client, _, _ = query_test_environment

    response = client.post(
        "/query",
        json={"question": "Missing?", "document_ids": [999999], "top_k": 5},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Requested document was not found."}


def test_query_unready_requested_document_returns_409(query_test_environment) -> None:
    client, _, _ = query_test_environment
    upload = client.post(
        "/documents/upload",
        files={"file": ("uploaded.pdf", ingestable_pdf_bytes(), "application/pdf")},
    )
    document_id = upload.json()["document"]["id"]

    response = client.post(
        "/query",
        json={"question": "Can I query this?", "document_ids": [document_id], "top_k": 5},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Requested document is not ready for querying."}


def test_query_without_ready_documents_returns_409(query_test_environment) -> None:
    client, _, _ = query_test_environment
    client.post(
        "/documents/upload",
        files={"file": ("uploaded.pdf", ingestable_pdf_bytes(), "application/pdf")},
    )

    response = client.post("/query", json={"question": "Anything available?"})

    assert response.status_code == 409
    assert response.json() == {"detail": "No ready documents are available for querying."}


def test_query_no_hit_path_skips_model(query_test_environment, monkeypatch) -> None:
    client, _, _ = query_test_environment
    document_id = _upload_and_ingest(client)

    def fake_search_chunks(**_kwargs) -> list[SearchResult]:
        return []

    def fail_run_query_agent(**_kwargs) -> AnswerResult:
        raise AssertionError("run_query_agent should not be called when retrieval has no hits")

    monkeypatch.setattr("app.services.query_service.search_chunks", fake_search_chunks)
    monkeypatch.setattr("app.services.query_service.run_query_agent", fail_run_query_agent)

    response = client.post(
        "/query",
        json={"question": "No evidence?", "document_ids": [document_id], "top_k": 5},
    )

    assert response.status_code == 200
    assert response.json() == {
        "answer": "I couldn't find relevant information in the indexed documents.",
        "citations": [],
        "confidence": 0.0,
    }


def test_query_returns_502_when_agent_fails(query_test_environment, monkeypatch) -> None:
    client, _, engine = query_test_environment
    document_id = _upload_and_ingest(client)
    chunk = _get_first_chunk(engine, document_id)

    def fake_search_chunks(**_kwargs) -> list[SearchResult]:
        return [_search_result_from_chunk(chunk, document_id)]

    def fake_run_query_agent(**_kwargs) -> AnswerResult:
        raise QueryAgentError("agent failed")

    monkeypatch.setattr("app.services.query_service.search_chunks", fake_search_chunks)
    monkeypatch.setattr("app.services.query_service.run_query_agent", fake_run_query_agent)

    response = client.post(
        "/query",
        json={"question": "Trigger failure", "document_ids": [document_id], "top_k": 5},
    )

    assert response.status_code == 502
    assert response.json() == {"detail": "agent failed"}


def test_query_returns_503_for_retrieval_dependency_failure(
    query_test_environment,
    monkeypatch,
    caplog,
) -> None:
    client, _, _ = query_test_environment
    document_id = _upload_and_ingest(client)

    def failing_search_chunks(**_kwargs) -> list[SearchResult]:
        raise OllamaNativeError("embedding backend unavailable\nextra context should not leak")

    monkeypatch.setattr("app.services.query_service.search_chunks", failing_search_chunks)

    with caplog.at_level(logging.INFO):
        response = client.post(
            "/query",
            json={"question": "Trigger dependency failure", "document_ids": [document_id]},
        )

    assert response.status_code == 503
    assert response.json() == {"detail": "embedding backend unavailable"}
    failure_logs = [record for record in caplog.records if record.msg == "query_failed"]
    assert any(record.stage == "retrieval" for record in failure_logs)


def test_query_logs_lifecycle_events(query_test_environment, monkeypatch, caplog) -> None:
    client, _, _ = query_test_environment
    document_id = _upload_and_ingest(client)

    def fake_search_chunks(**_kwargs) -> list[SearchResult]:
        return []

    monkeypatch.setattr("app.services.query_service.search_chunks", fake_search_chunks)

    with caplog.at_level(logging.INFO):
        response = client.post(
            "/query",
            json={"question": "No evidence?", "document_ids": [document_id], "top_k": 5},
        )

    assert response.status_code == 200
    events = [record.msg for record in caplog.records]
    assert "query_started" in events
    assert "query_completed" in events


def test_query_agent_uses_tools_and_returns_grounded_citations(
    query_test_environment,
    monkeypatch,
    caplog,
) -> None:
    _, settings, engine = query_test_environment

    with caplog.at_level(logging.INFO):
        with Session(engine) as session:
            document = Document(
                filename="agent.pdf",
                file_path="./data/uploads/agent.pdf",
                checksum="agent-checksum",
                page_count=1,
                status="ready",
            )
            session.add(document)
            session.commit()
            session.refresh(document)
            assert document.id is not None

            chunk = DocumentChunk(
                document_id=document.id,
                chunk_index=0,
                page_number=1,
                section_title="Overview",
                text="The query pipeline must stay grounded in fetched chunk context.",
                token_estimate=12,
                metadata_json={},
                embedding=_embedding_for_text("agent-question", settings.embedding_dimension),
            )
            session.add(chunk)
            session.commit()
            session.refresh(chunk)
            assert chunk.id is not None
            assert chunk.embedding is not None
            chunk_embedding = list(chunk.embedding)

            def fake_query_embed(_texts: list[str], _settings: Settings) -> list[list[float]]:
                return [chunk_embedding]

            monkeypatch.setattr("app.retrieval.search.embed_texts", fake_query_embed)

            def function_model(messages, info: AgentInfo) -> ModelResponse:
                last_request = messages[-1]
                assert isinstance(last_request, ModelRequest)
                tool_returns = [
                    part for part in last_request.parts if isinstance(part, ToolReturnPart)
                ]
                if not tool_returns:
                    return ModelResponse(
                        parts=[
                            ToolCallPart(
                                "search_chunks",
                                {
                                    "query": "agent-question",
                                    "document_ids": [document.id],
                                    "top_k": 5,
                                },
                            )
                        ]
                    )

                last_tool_return = tool_returns[-1]
                if last_tool_return.tool_name == "search_chunks":
                    content = last_tool_return.content
                    assert isinstance(content, list)
                    chunk_id = content[0].chunk_id
                    return ModelResponse(
                        parts=[
                            ToolCallPart(
                                "fetch_chunk_context",
                                {"chunk_ids": [chunk_id]},
                            )
                        ]
                    )

                output_tool_name = info.output_tools[0].name
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            output_tool_name,
                            {
                                "answer": "The pipeline stays grounded in fetched chunk context.",
                                "citations": [
                                    {
                                        "document_id": document.id,
                                        "chunk_id": chunk.id,
                                        "filename": "agent.pdf",
                                        "page_number": 1,
                                        "section_title": "Overview",
                                        "quote": "must stay grounded in fetched chunk context",
                                    }
                                ],
                                "confidence": 0.88,
                            },
                        )
                    ]
                )

            model = FunctionModel(function=function_model)
            agent = build_query_agent(settings, model=model)
            deps = QueryAgentDeps(
                session=session,
                settings=settings,
                document_ids=[document.id],
                top_k=5,
            )

            result = agent.run_sync("agent-question", deps=deps)

    assert result.output.answer == "The pipeline stays grounded in fetched chunk context."
    assert chunk.id in deps.search_results_by_id
    assert chunk.id in deps.fetched_chunks_by_id
    tool_logs = [record for record in caplog.records if record.msg == "agent_tool_called"]
    assert [record.tool_name for record in tool_logs] == [
        "search_chunks",
        "fetch_chunk_context",
    ]


def test_run_query_agent_rejects_invalid_citations(query_test_environment, monkeypatch) -> None:
    _, settings, engine = query_test_environment

    with Session(engine) as session:
        document = Document(
            filename="invalid.pdf",
            file_path="./data/uploads/invalid.pdf",
            checksum="invalid-checksum",
            page_count=1,
            status="ready",
        )
        session.add(document)
        session.commit()
        session.refresh(document)
        assert document.id is not None

        chunk = DocumentChunk(
            document_id=document.id,
            chunk_index=0,
            page_number=1,
            section_title="Overview",
            text="Only fetched chunk quotes are valid.",
            token_estimate=8,
            metadata_json={},
            embedding=_embedding_for_text("invalid-question", settings.embedding_dimension),
        )
        session.add(chunk)
        session.commit()
        session.refresh(chunk)
        assert chunk.id is not None
        assert chunk.embedding is not None
        chunk_embedding = list(chunk.embedding)

        def fake_query_embed(_texts: list[str], _settings: Settings) -> list[list[float]]:
            return [chunk_embedding]

        monkeypatch.setattr("app.retrieval.search.embed_texts", fake_query_embed)

        with pytest.raises(QueryAgentError):
            run_query_agent(
                session=session,
                settings=settings,
                question="invalid-question",
                document_ids=[document.id],
                top_k=5,
                model_override=TestModel(
                    call_tools=["search_chunks", "fetch_chunk_context"],
                    custom_output_args={
                        "answer": "Invalid citation output.",
                        "citations": [
                            {
                                "document_id": document.id,
                                "chunk_id": chunk.id,
                                "filename": "invalid.pdf",
                                "page_number": 1,
                                "section_title": "Overview",
                                "quote": "not present in the chunk text",
                            }
                        ],
                        "confidence": 0.6,
                    },
                ),
            )


@pytest.mark.integration
def test_query_integration_returns_citations_when_chat_available(
    query_test_environment,
    monkeypatch,
) -> None:
    client, settings, engine = query_test_environment
    document_id = _upload_and_ingest(client)
    chunk = _get_first_chunk(engine, document_id)
    assert chunk.embedding is not None
    chunk_embedding = list(chunk.embedding)

    try:
        check_anthropic_compat(settings)
    except Exception as exc:
        pytest.skip(f"Ollama chat not available for integration test: {exc}")

    def fake_query_embed(_texts: list[str], _settings: Settings) -> list[list[float]]:
        return [chunk_embedding]

    monkeypatch.setattr("app.retrieval.search.embed_texts", fake_query_embed)

    response = client.post(
        "/query",
        json=QueryRequest(
            question="What should the agent avoid fabricating?",
            document_ids=[document_id],
            top_k=5,
        ).model_dump(),
    )

    if response.status_code in {502, 503}:
        pytest.skip(f"Ollama live query was unavailable for integration test: {response.json()}")

    assert response.status_code == 200
    assert response.json()["citations"]
