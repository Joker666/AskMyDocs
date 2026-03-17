from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from sqlmodel import Session, select

from app.config import Settings
from app.db.models import Document, DocumentChunk, IngestionJob
from app.db.session import get_engine
from app.ingestion.chunker import chunk_document
from app.ingestion.embedder import embed_texts
from app.ingestion.parser import ParsedDocument, parse_document
from app.observability import start_observation
from app.runtime import safe_error_detail

logger = logging.getLogger(__name__)


class IngestionPipelineError(Exception):
    """Raised when ingestion cannot complete successfully."""


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _artifact_path(settings: Settings, document_id: int) -> Path:
    return Path(settings.parsed_dir) / f"{document_id}.json"


def run_ingestion_job(settings: Settings, document_id: int, job_id: int) -> None:
    with start_observation(
        settings,
        name="documents.ingest.run",
        as_type="chain",
        input={"document_id": document_id, "job_id": job_id},
        metadata={"component": "ingestion_pipeline"},
    ) as span:
        engine = get_engine(settings)
        artifact_path = _artifact_path(settings, document_id)
        artifact_temp_path = artifact_path.with_suffix(".json.tmp")
        preserve_existing_index = False

        try:
            with Session(engine) as session:
                document, job = _load_document_and_job(
                    session=session,
                    document_id=document_id,
                    job_id=job_id,
                )
                source_path = Path(document.file_path)
                if not source_path.exists():
                    raise IngestionPipelineError("Document source file is missing.")

                preserve_existing_index = _has_queryable_index(
                    session=session,
                    document_id=document_id,
                )

                job.status = "running"
                job.started_at = _utcnow()
                job.error_message = None
                document.status = "ingesting"
                document.updated_at = _utcnow()
                document_filename = document.filename
                document_file_path = document.file_path
                logger.info(
                    "ingestion_started",
                    extra={
                        "document_id": document_id,
                        "job_id": job_id,
                        "preserve_existing_index": preserve_existing_index,
                    },
                )
                session.add(document)
                session.add(job)
                session.commit()

            parsed_document = parse_document(
                document_id=document_id,
                filename=document_filename,
                source_path=document_file_path,
            )
            _write_parsed_artifact(artifact_temp_path, parsed_document)

            chunks = chunk_document(document_id=document_id, parsed_document=parsed_document)
            if not chunks:
                raise IngestionPipelineError("No chunkable text found.")
            embeddings = embed_texts([chunk.text for chunk in chunks], settings)
            if len(embeddings) != len(chunks):
                raise IngestionPipelineError("Embedding count did not match chunk count.")

            with Session(engine) as session:
                document, job = _load_document_and_job(
                    session=session,
                    document_id=document_id,
                    job_id=job_id,
                )

                existing_chunks = session.exec(
                    select(DocumentChunk).where(DocumentChunk.document_id == document_id)
                ).all()
                for existing_chunk in existing_chunks:
                    session.delete(existing_chunk)
                session.flush()
                for chunk in chunks:
                    session.add(
                        DocumentChunk(
                            document_id=document_id,
                            chunk_index=chunk.chunk_index,
                            page_number=chunk.page_number,
                            section_title=chunk.section_title,
                            text=chunk.text,
                            token_estimate=chunk.token_estimate,
                            metadata_json=chunk.metadata_json,
                            embedding=embeddings[chunk.chunk_index],
                        )
                    )

                document.page_count = parsed_document.page_count
                document.status = "ready"
                document.updated_at = _utcnow()
                job.status = "completed"
                job.completed_at = _utcnow()
                job.error_message = None

                session.add(document)
                session.add(job)
                session.commit()

            artifact_temp_path.replace(artifact_path)
            logger.info(
                "ingestion_completed",
                extra={
                    "document_id": document_id,
                    "job_id": job_id,
                    "chunk_count": len(chunks),
                    "page_count": parsed_document.page_count,
                },
            )
            if span is not None:
                span.update(
                    output={
                        "chunk_count": len(chunks),
                        "page_count": parsed_document.page_count,
                        "preserve_existing_index": preserve_existing_index,
                    }
                )
        except Exception as exc:
            if artifact_temp_path.exists():
                artifact_temp_path.unlink(missing_ok=True)
            if span is not None:
                span.update(
                    level="ERROR",
                    status_message=safe_error_detail(exc, fallback="Ingestion failed."),
                )
            _mark_ingestion_failed(
                settings=settings,
                document_id=document_id,
                job_id=job_id,
                error=exc,
                preserve_ready_document=preserve_existing_index,
            )


def _load_document_and_job(
    *,
    session: Session,
    document_id: int,
    job_id: int,
) -> tuple[Document, IngestionJob]:
    document = session.get(Document, document_id)
    job = session.get(IngestionJob, job_id)
    if document is None or job is None or document.id is None or job.id is None:
        raise IngestionPipelineError("Ingestion job context is missing.")
    return document, job


def _write_parsed_artifact(path: Path, parsed_document: ParsedDocument) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(parsed_document.model_dump_json(indent=2), encoding="utf-8")


def _has_queryable_index(*, session: Session, document_id: int) -> bool:
    embedding_column = cast(Any, DocumentChunk.embedding)
    existing_chunk = session.exec(
        select(DocumentChunk.id)
        .where(DocumentChunk.document_id == document_id)
        .where(embedding_column.is_not(None))
        .limit(1)
    ).first()
    return existing_chunk is not None


def _mark_ingestion_failed(
    *,
    settings: Settings,
    document_id: int,
    job_id: int,
    error: Exception,
    preserve_ready_document: bool = False,
) -> None:
    engine = get_engine(settings)
    message = error.args[0] if error.args else str(error)
    short_message = safe_error_detail(
        message or error.__class__.__name__,
        fallback="Document ingestion failed.",
    )

    with Session(engine) as session:
        document = session.get(Document, document_id)
        job = session.get(IngestionJob, job_id)

        if document is not None:
            document.status = "ready" if preserve_ready_document else "failed"
            document.updated_at = _utcnow()
            session.add(document)

        if job is not None:
            if job.started_at is None:
                job.started_at = _utcnow()
            job.status = "failed"
            job.completed_at = _utcnow()
            job.error_message = short_message
            session.add(job)

        session.commit()

    logger.warning(
        "ingestion_failed",
        extra={
            "document_id": document_id,
            "job_id": job_id,
            "error_detail": short_message,
            "preserve_ready_document": preserve_ready_document,
        },
    )
