from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlmodel import Session, delete, select

from app.config import Settings
from app.db.models import Document, DocumentChunk, IngestionJob
from app.db.session import get_engine
from app.dependencies import get_app_settings, get_db_session
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


def pdf_bytes(title: str = "Sample") -> bytes:
    return (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Count 1 /Kids [3 0 R] >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 144] >>\nendobj\n"
        b"trailer\n<< /Root 1 0 R >>\n%%EOF\n"
        + title.encode("utf-8")
    )


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
