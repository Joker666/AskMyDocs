from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, desc, select

from app.config import Settings
from app.db.models import Document, DocumentChunk, IngestionJob
from app.db.schemas import (
    DocumentDetailResponse,
    DocumentListResponse,
    DocumentSummary,
    DocumentUploadResponse,
    IngestionStatusResponse,
)
from app.runtime import safe_error_detail

logger = logging.getLogger(__name__)


class DocumentServiceError(Exception):
    """Base service exception for document operations."""


class DocumentNotFoundError(DocumentServiceError):
    """Raised when a document does not exist."""


class InvalidPdfUploadError(DocumentServiceError):
    """Raised when an uploaded file is not a valid PDF."""


class DocumentIngestionConflictError(DocumentServiceError):
    """Raised when a document cannot begin ingestion in its current state."""


@dataclass(frozen=True)
class UploadResult:
    document: Document
    created: bool


@dataclass(frozen=True)
class IngestionStartResult:
    document: Document
    job: IngestionJob
def _utcnow() -> datetime:
    return datetime.now(UTC)


def validate_pdf_upload(*, filename: str | None, content_type: str | None, content: bytes) -> None:
    if not filename or not filename.lower().endswith(".pdf"):
        raise InvalidPdfUploadError(
            safe_error_detail("Only PDF files are supported.", fallback="Invalid PDF upload.")
        )

    if content_type != "application/pdf":
        raise InvalidPdfUploadError(
            safe_error_detail(
                "Upload content type must be application/pdf.",
                fallback="Invalid PDF upload.",
            )
        )

    if not content.startswith(b"%PDF-"):
        raise InvalidPdfUploadError(
            safe_error_detail(
                "Uploaded file content is not a valid PDF.",
                fallback="Invalid PDF upload.",
            )
        )


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
        chunk_count=_chunk_count(session, document_id) if job.status == "completed" else 0,
    )


def _chunk_count(session: Session, document_id: int) -> int:
    statement = select(DocumentChunk).where(DocumentChunk.document_id == document_id)
    return len(session.exec(statement).all())


def _source_path(document: Document) -> Path:
    return Path(document.file_path)


def upload_document(
    *,
    session: Session,
    settings: Settings,
    filename: str | None,
    content_type: str | None,
    content: bytes,
) -> UploadResult:
    logger.info(
        "document_upload_started",
        extra={
            "upload_filename": filename or "<missing>",
            "content_type": content_type or "<missing>",
            "size_bytes": len(content),
        },
    )
    validate_pdf_upload(filename=filename, content_type=content_type, content=content)
    checksum = compute_checksum(content)

    existing = session.exec(select(Document).where(Document.checksum == checksum)).first()
    if existing is not None:
        logger.info(
            "document_upload_completed",
            extra={
                "document_id": existing.id,
                "was_created": False,
                "checksum": checksum,
            },
        )
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
            logger.info(
                "document_upload_completed",
                extra={
                    "document_id": existing.id,
                    "was_created": False,
                    "checksum": checksum,
                },
            )
            return UploadResult(document=existing, created=False)
        raise

    session.refresh(document)
    logger.info(
        "document_upload_completed",
        extra={
            "document_id": document.id,
            "was_created": True,
            "checksum": checksum,
        },
    )
    return UploadResult(document=document, created=True)


def list_documents(*, session: Session) -> DocumentListResponse:
    statement = select(Document).order_by(desc(Document.created_at), desc(Document.id))
    documents = session.exec(statement).all()
    return DocumentListResponse(documents=[_document_summary(document) for document in documents])


def get_document_detail(*, session: Session, document_id: int) -> DocumentDetailResponse:
    document = session.get(Document, document_id)
    if document is None or document.id is None:
        raise DocumentNotFoundError(
            safe_error_detail("Document not found.", fallback="Document not found.")
        )
    if document.created_at is None or document.updated_at is None:
        raise DocumentServiceError(
            safe_error_detail(
                "Document timestamps are missing.",
                fallback="Document metadata is incomplete.",
            )
        )

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


def get_document_record(*, session: Session, document_id: int) -> Document:
    document = session.get(Document, document_id)
    if document is None or document.id is None:
        raise DocumentNotFoundError(
            safe_error_detail("Document not found.", fallback="Document not found.")
        )
    return document


def start_document_ingestion(*, session: Session, document_id: int) -> IngestionStartResult:
    document = get_document_record(session=session, document_id=document_id)

    if not _source_path(document).exists():
        raise DocumentIngestionConflictError(
            safe_error_detail(
                "Document source file is missing.",
                fallback="Document source file is missing.",
            )
        )

    active_job = session.exec(
        select(IngestionJob)
        .where(IngestionJob.document_id == document_id)
        .where(col(IngestionJob.status).in_(("pending", "running")))
        .order_by(desc(IngestionJob.created_at), desc(IngestionJob.id))
    ).first()
    if active_job is not None:
        raise DocumentIngestionConflictError(
            safe_error_detail(
                "Document ingestion is already in progress.",
                fallback="Document ingestion is already in progress.",
            )
        )

    job = IngestionJob(
        document_id=document_id,
        status="pending",
        error_message=None,
        started_at=None,
        completed_at=None,
    )
    session.add(job)
    document.updated_at = _utcnow()
    session.add(document)
    session.commit()
    session.refresh(job)
    session.refresh(document)
    logger.info(
        "ingestion_requested",
        extra={
            "document_id": document.id,
            "job_id": job.id,
            "document_status": document.status,
        },
    )
    return IngestionStartResult(document=document, job=job)


def ingestion_status_response(
    job: IngestionJob,
    *,
    chunk_count: int = 0,
) -> IngestionStatusResponse:
    if job.id is None:
        raise DocumentServiceError(
            safe_error_detail(
                "Ingestion job is missing an identifier.",
                fallback="Ingestion job is missing an identifier.",
            )
        )

    return IngestionStatusResponse(
        job_id=job.id,
        document_id=job.document_id,
        status=job.status,
        error_message=job.error_message,
        started_at=job.started_at,
        completed_at=job.completed_at,
        chunk_count=chunk_count,
    )
