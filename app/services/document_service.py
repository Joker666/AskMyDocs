from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, desc, select

from app.config import Settings
from app.db.models import Document, DocumentChunk, IngestionJob
from app.db.schemas import (
    DocumentDetailResponse,
    DocumentListResponse,
    DocumentSummary,
    DocumentUploadResponse,
    IngestionStatusResponse,
)


class DocumentServiceError(Exception):
    """Base service exception for document operations."""


class DocumentNotFoundError(DocumentServiceError):
    """Raised when a document does not exist."""


class InvalidPdfUploadError(DocumentServiceError):
    """Raised when an uploaded file is not a valid PDF."""


@dataclass(frozen=True)
class UploadResult:
    document: Document
    created: bool


def _short_error(message: str) -> str:
    return message.strip()[:200]


def validate_pdf_upload(*, filename: str | None, content_type: str | None, content: bytes) -> None:
    if not filename or not filename.lower().endswith(".pdf"):
        raise InvalidPdfUploadError(_short_error("Only PDF files are supported."))

    if content_type != "application/pdf":
        raise InvalidPdfUploadError(_short_error("Upload content type must be application/pdf."))

    if not content.startswith(b"%PDF-"):
        raise InvalidPdfUploadError(_short_error("Uploaded file content is not a valid PDF."))


def compute_checksum(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _storage_path(settings: Settings, checksum: str) -> Path:
    return Path(settings.upload_dir) / f"{checksum}.pdf"


def _storage_reference(settings: Settings, checksum: str) -> str:
    return f"{settings.upload_dir.rstrip('/')}/{checksum}.pdf"


def _document_summary(document: Document) -> DocumentSummary:
    return DocumentSummary.model_validate(document)


def _latest_ingestion(session: Session, document_id: int) -> IngestionStatusResponse | None:
    statement = (
        select(IngestionJob)
        .where(IngestionJob.document_id == document_id)
        .order_by(desc(IngestionJob.created_at), desc(IngestionJob.id))
        .limit(1)
    )
    job = session.exec(statement).first()
    if job is None or job.id is None:
        return None

    return IngestionStatusResponse(
        job_id=job.id,
        document_id=job.document_id,
        status=job.status,
        error_message=job.error_message,
        started_at=job.started_at,
        completed_at=job.completed_at,
        chunk_count=_chunk_count(session, document_id),
    )


def _chunk_count(session: Session, document_id: int) -> int:
    statement = select(DocumentChunk).where(DocumentChunk.document_id == document_id)
    return len(session.exec(statement).all())


def upload_document(
    *,
    session: Session,
    settings: Settings,
    filename: str | None,
    content_type: str | None,
    content: bytes,
) -> UploadResult:
    validate_pdf_upload(filename=filename, content_type=content_type, content=content)
    checksum = compute_checksum(content)

    existing = session.exec(select(Document).where(Document.checksum == checksum)).first()
    if existing is not None:
        return UploadResult(document=existing, created=False)

    storage_path = _storage_path(settings, checksum)
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    storage_path.write_bytes(content)

    document = Document(
        filename=filename or f"{checksum}.pdf",
        file_path=_storage_reference(settings, checksum),
        checksum=checksum,
        page_count=None,
        status="uploaded",
    )
    session.add(document)

    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.exec(select(Document).where(Document.checksum == checksum)).first()
        if existing is not None:
            return UploadResult(document=existing, created=False)
        raise

    session.refresh(document)
    return UploadResult(document=document, created=True)


def list_documents(*, session: Session) -> DocumentListResponse:
    statement = select(Document).order_by(desc(Document.created_at), desc(Document.id))
    documents = session.exec(statement).all()
    return DocumentListResponse(documents=[_document_summary(document) for document in documents])


def get_document_detail(*, session: Session, document_id: int) -> DocumentDetailResponse:
    document = session.get(Document, document_id)
    if document is None or document.id is None:
        raise DocumentNotFoundError(_short_error("Document not found."))
    if document.created_at is None or document.updated_at is None:
        raise DocumentServiceError(_short_error("Document timestamps are missing."))

    return DocumentDetailResponse(
        id=document.id,
        filename=document.filename,
        file_path=document.file_path,
        checksum=document.checksum,
        page_count=document.page_count,
        status=document.status,
        chunk_count=_chunk_count(session, document.id),
        created_at=document.created_at,
        updated_at=document.updated_at,
        latest_ingestion=_latest_ingestion(session, document.id),
    )


def document_upload_response(document: Document) -> DocumentUploadResponse:
    return DocumentUploadResponse(document=_document_summary(document))
