from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, cast

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, delete, select

from app.config import Settings
from app.db.models import Document, DocumentChunk, IngestionJob
from app.db.session import get_engine
from app.dependencies import get_app_settings, get_db_session
from app.ingestion.embedder import OllamaNativeError
from app.ingestion.parser import DocumentParseError, parse_document
from app.main import app


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
def document_test_environment(tmp_path):
    settings = make_settings(tmp_path / "uploads", tmp_path / "parsed")
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.parsed_dir).mkdir(parents=True, exist_ok=True)

    try:
        with psycopg.connect(settings.migration_database_url):
            pass
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres not available for document tests: {exc}")

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


def pdf_bytes(title: str = "Sample") -> bytes:
    return build_pdf([[title, "Short PDF body for upload validation."]])


def ingestable_pdf_bytes() -> bytes:
    page_one = [
        "Phase 3 Parser Title",
        " ".join(f"page1-token-{idx:03d}" for idx in range(80)),
    ]
    page_two = [
        "Phase 3 Parser Continuation",
        " ".join(f"page2-token-{idx:03d}" for idx in range(80)),
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


def test_upload_valid_pdf_creates_document(document_test_environment) -> None:
    client, settings, engine = document_test_environment

    response = client.post(
        "/documents/upload",
        files={"file": ("paper.pdf", pdf_bytes(), "application/pdf")},
    )

    assert response.status_code == 201
    payload = response.json()["document"]
    checksum = next(Path(settings.upload_dir).glob("*.pdf")).stem

    assert payload["filename"] == "paper.pdf"
    assert payload["status"] == "uploaded"

    stored_file = Path(settings.upload_dir) / f"{checksum}.pdf"
    assert stored_file.exists()

    with Session(engine) as session:
        documents = session.exec(select(Document)).all()
        assert len(documents) == 1
        assert documents[0].file_path == f"{settings.upload_dir}/{checksum}.pdf"


def test_duplicate_upload_returns_existing_document(document_test_environment) -> None:
    client, settings, engine = document_test_environment
    content = pdf_bytes("duplicate")

    first = client.post(
        "/documents/upload",
        files={"file": ("paper.pdf", content, "application/pdf")},
    )
    second = client.post(
        "/documents/upload",
        files={"file": ("paper-again.pdf", content, "application/pdf")},
    )

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["document"]["id"] == second.json()["document"]["id"]

    assert len(list(Path(settings.upload_dir).glob("*.pdf"))) == 1
    with Session(engine) as session:
        documents = session.exec(select(Document)).all()
        assert len(documents) == 1


def test_upload_rejects_non_pdf_extension(document_test_environment) -> None:
    client, _, _ = document_test_environment

    response = client.post(
        "/documents/upload",
        files={"file": ("notes.txt", pdf_bytes(), "application/pdf")},
    )

    assert response.status_code == 415
    assert response.json() == {"detail": "Only PDF files are supported."}


def test_upload_rejects_non_pdf_content_type(document_test_environment) -> None:
    client, _, _ = document_test_environment

    response = client.post(
        "/documents/upload",
        files={"file": ("paper.pdf", pdf_bytes(), "text/plain")},
    )

    assert response.status_code == 415
    assert response.json() == {"detail": "Upload content type must be application/pdf."}


def test_upload_rejects_invalid_pdf_magic_header(document_test_environment) -> None:
    client, _, _ = document_test_environment

    response = client.post(
        "/documents/upload",
        files={"file": ("paper.pdf", b"not-a-pdf", "application/pdf")},
    )

    assert response.status_code == 415
    assert response.json() == {"detail": "Uploaded file content is not a valid PDF."}


def test_get_documents_returns_newest_first(document_test_environment) -> None:
    client, _, _ = document_test_environment

    first = client.post(
        "/documents/upload",
        files={"file": ("first.pdf", pdf_bytes("first"), "application/pdf")},
    )
    second = client.post(
        "/documents/upload",
        files={"file": ("second.pdf", pdf_bytes("second"), "application/pdf")},
    )

    response = client.get("/documents")

    assert response.status_code == 200
    documents = response.json()["documents"]
    assert [doc["id"] for doc in documents] == [
        second.json()["document"]["id"],
        first.json()["document"]["id"],
    ]


def test_get_document_detail_returns_expected_shape(document_test_environment) -> None:
    client, settings, _ = document_test_environment

    upload = client.post(
        "/documents/upload",
        files={"file": ("paper.pdf", pdf_bytes(), "application/pdf")},
    )
    document = upload.json()["document"]
    checksum = next(Path(settings.upload_dir).glob("*.pdf")).stem

    response = client.get(f"/documents/{document['id']}")

    assert response.status_code == 200
    assert response.json() == {
        "id": document["id"],
        "filename": "paper.pdf",
        "file_path": f"{settings.upload_dir}/{checksum}.pdf",
        "checksum": checksum,
        "page_count": None,
        "status": "uploaded",
        "chunk_count": 0,
        "created_at": document["created_at"],
        "updated_at": document["updated_at"],
        "latest_ingestion": None,
    }


def test_get_document_detail_returns_404_for_missing_document(document_test_environment) -> None:
    client, _, _ = document_test_environment

    response = client.get("/documents/999999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Document not found."}


def test_parser_normalizes_docling_output(document_test_environment) -> None:
    _, settings, _ = document_test_environment
    source_path = Path(settings.upload_dir) / "parser-sample.pdf"
    source_path.write_bytes(ingestable_pdf_bytes())

    parsed = parse_document(document_id=1, filename="parser-sample.pdf", source_path=source_path)

    assert parsed.document_id == 1
    assert parsed.page_count == 2
    assert parsed.pages[0].page_number == 1
    assert parsed.pages[1].page_number == 2
    assert any("Phase 3 Parser Title" in block.text for block in parsed.pages[0].blocks)


def test_ingest_document_runs_background_pipeline(document_test_environment) -> None:
    client, settings, engine = document_test_environment

    upload = client.post(
        "/documents/upload",
        files={"file": ("ingestable.pdf", ingestable_pdf_bytes(), "application/pdf")},
    )
    document_id = upload.json()["document"]["id"]

    response = client.post(f"/documents/{document_id}/ingest")

    assert response.status_code == 202
    assert response.json()["status"] == "pending"
    assert response.json()["chunk_count"] == 0

    detail = client.get(f"/documents/{document_id}")
    assert detail.status_code == 200
    body = detail.json()

    assert body["status"] == "ready"
    assert body["page_count"] == 2
    assert body["chunk_count"] > 0
    assert body["latest_ingestion"]["status"] == "completed"

    parsed_artifact = Path(settings.parsed_dir) / f"{document_id}.json"
    assert parsed_artifact.exists()
    artifact_body = json.loads(parsed_artifact.read_text(encoding="utf-8"))
    assert artifact_body["document_id"] == document_id
    assert artifact_body["page_count"] == 2

    with Session(engine) as session:
        chunks = session.exec(
            select(DocumentChunk).where(DocumentChunk.document_id == document_id)
        ).all()
        assert len(chunks) == body["chunk_count"]
        assert all(chunk.embedding is not None for chunk in chunks)
        assert all(
            len(chunk.embedding) == settings.embedding_dimension
            for chunk in chunks
            if chunk.embedding is not None
        )


def test_reingest_replaces_existing_chunks(document_test_environment) -> None:
    client, _, engine = document_test_environment

    upload = client.post(
        "/documents/upload",
        files={"file": ("reingest.pdf", ingestable_pdf_bytes(), "application/pdf")},
    )
    document_id = upload.json()["document"]["id"]

    first = client.post(f"/documents/{document_id}/ingest")
    second = client.post(f"/documents/{document_id}/ingest")

    assert first.status_code == 202
    assert second.status_code == 202

    with Session(engine) as session:
        chunks = session.exec(
            select(DocumentChunk).where(DocumentChunk.document_id == document_id)
        ).all()
        jobs = session.exec(
            select(IngestionJob).where(IngestionJob.document_id == document_id)
        ).all()
        assert len(chunks) > 0
        assert len(jobs) == 2

    detail = client.get(f"/documents/{document_id}")
    assert detail.json()["latest_ingestion"]["status"] == "completed"
    assert detail.json()["chunk_count"] == len(chunks)


def test_ingest_missing_document_returns_404(document_test_environment) -> None:
    client, _, _ = document_test_environment

    response = client.post("/documents/999999/ingest")

    assert response.status_code == 404
    assert response.json() == {"detail": "Document not found."}


def test_ingest_conflicts_with_running_job(document_test_environment) -> None:
    client, _, engine = document_test_environment

    upload = client.post(
        "/documents/upload",
        files={"file": ("conflict.pdf", ingestable_pdf_bytes(), "application/pdf")},
    )
    document_id = upload.json()["document"]["id"]

    with Session(engine) as session:
        session.add(IngestionJob(document_id=document_id, status="running"))
        session.commit()

    response = client.post(f"/documents/{document_id}/ingest")

    assert response.status_code == 409
    assert response.json() == {"detail": "Document ingestion is already in progress."}


def test_ingest_rejects_missing_source_file(document_test_environment) -> None:
    client, settings, _ = document_test_environment

    upload = client.post(
        "/documents/upload",
        files={"file": ("missing-source.pdf", ingestable_pdf_bytes(), "application/pdf")},
    )
    document_id = upload.json()["document"]["id"]

    stored_file = next(Path(settings.upload_dir).glob("*.pdf"))
    stored_file.unlink()

    response = client.post(f"/documents/{document_id}/ingest")

    assert response.status_code == 409
    assert response.json() == {"detail": "Document source file is missing."}


def test_ingest_failure_marks_job_and_document_failed(
    document_test_environment,
    monkeypatch,
    caplog,
) -> None:
    client, settings, engine = document_test_environment

    def fake_parse_document(*, document_id: int, filename: str, source_path: str | Path):
        raise DocumentParseError(
            "Docling parsing failed because the test forced an error.\ntraceback line"
        )

    monkeypatch.setattr("app.ingestion.pipeline.parse_document", fake_parse_document)

    upload = client.post(
        "/documents/upload",
        files={"file": ("failing.pdf", ingestable_pdf_bytes(), "application/pdf")},
    )
    document_id = upload.json()["document"]["id"]

    with caplog.at_level(logging.INFO):
        response = client.post(f"/documents/{document_id}/ingest")

    assert response.status_code == 202

    detail = client.get(f"/documents/{document_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == "failed"
    assert body["chunk_count"] == 0
    assert body["latest_ingestion"]["status"] == "failed"
    assert len(body["latest_ingestion"]["error_message"]) <= 200
    assert body["latest_ingestion"]["error_message"] == (
        "Docling parsing failed because the test forced an error."
    )

    artifact_path = Path(settings.parsed_dir) / f"{document_id}.json"
    assert not artifact_path.exists()

    with Session(engine) as session:
        chunks = session.exec(
            select(DocumentChunk).where(DocumentChunk.document_id == document_id)
        ).all()
        assert chunks == []
    failure_logs = [record for record in caplog.records if record.msg == "ingestion_failed"]
    assert len(failure_logs) == 1
    assert failure_logs[0].document_id == document_id


def test_ingest_logs_started_and_completed(document_test_environment, caplog) -> None:
    client, _, _ = document_test_environment

    upload = client.post(
        "/documents/upload",
        files={"file": ("logging.pdf", ingestable_pdf_bytes(), "application/pdf")},
    )
    document_id = upload.json()["document"]["id"]

    with caplog.at_level(logging.INFO):
        response = client.post(f"/documents/{document_id}/ingest")

    assert response.status_code == 202
    events = [record.msg for record in caplog.records]
    assert "ingestion_requested" in events
    assert "ingestion_started" in events
    assert "ingestion_completed" in events


def test_ingest_route_returns_503_for_start_failure(document_test_environment, monkeypatch) -> None:
    client, _, _ = document_test_environment

    def failing_start_document_ingestion(*, session, settings, document_id: int):
        raise SQLAlchemyError("database write failed\ninternal details")

    monkeypatch.setattr(
        "app.api.routes_documents.start_document_ingestion",
        failing_start_document_ingestion,
    )

    response = client.post("/documents/1/ingest")

    assert response.status_code == 503
    assert response.json() == {"detail": "database write failed"}


def test_ingest_embedding_failure_marks_job_and_document_failed(
    document_test_environment,
    monkeypatch,
) -> None:
    client, _, engine = document_test_environment

    def fake_embed_texts(_texts: list[str], _settings: Settings) -> list[list[float]]:
        raise OllamaNativeError("embedding model unavailable")

    monkeypatch.setattr("app.ingestion.pipeline.embed_texts", fake_embed_texts)

    upload = client.post(
        "/documents/upload",
        files={"file": ("embedding-failure.pdf", ingestable_pdf_bytes(), "application/pdf")},
    )
    document_id = upload.json()["document"]["id"]

    response = client.post(f"/documents/{document_id}/ingest")

    assert response.status_code == 202

    detail = client.get(f"/documents/{document_id}")
    body = detail.json()
    assert body["status"] == "failed"
    assert body["chunk_count"] == 0
    assert body["latest_ingestion"]["status"] == "failed"
    assert body["latest_ingestion"]["error_message"] == "embedding model unavailable"

    with Session(engine) as session:
        chunks = session.exec(
            select(DocumentChunk).where(DocumentChunk.document_id == document_id)
        ).all()
        assert chunks == []


def test_reingest_embedding_failure_keeps_last_good_index(
    document_test_environment,
    monkeypatch,
) -> None:
    client, settings, engine = document_test_environment

    upload = client.post(
        "/documents/upload",
        files={"file": ("reingest-failure.pdf", ingestable_pdf_bytes(), "application/pdf")},
    )
    document_id = upload.json()["document"]["id"]

    first = client.post(f"/documents/{document_id}/ingest")
    assert first.status_code == 202

    with Session(engine) as session:
        existing_chunks = session.exec(
            select(DocumentChunk).where(DocumentChunk.document_id == document_id)
        ).all()
        assert len(existing_chunks) > 0
        existing_chunk_count = len(existing_chunks)
        existing_embeddings = [
            list(chunk.embedding) if chunk.embedding is not None else None
            for chunk in existing_chunks
        ]

    def fake_embed_texts(_texts: list[str], _settings: Settings) -> list[list[float]]:
        raise OllamaNativeError("embedding service unavailable")

    monkeypatch.setattr("app.ingestion.pipeline.embed_texts", fake_embed_texts)

    second = client.post(f"/documents/{document_id}/ingest")

    assert second.status_code == 202

    detail = client.get(f"/documents/{document_id}")
    body = detail.json()
    assert body["status"] == "ready"
    assert body["chunk_count"] == existing_chunk_count
    assert body["latest_ingestion"]["status"] == "failed"
    assert body["latest_ingestion"]["error_message"] == "embedding service unavailable"

    with Session(engine) as session:
        chunks = session.exec(
            select(DocumentChunk).where(DocumentChunk.document_id == document_id)
        ).all()
        assert len(chunks) == existing_chunk_count
        assert [
            list(chunk.embedding) if chunk.embedding is not None else None
            for chunk in chunks
        ] == existing_embeddings
        assert all(
            len(chunk.embedding) == settings.embedding_dimension
            for chunk in chunks
            if chunk.embedding is not None
        )
