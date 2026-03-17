from __future__ import annotations

from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from app.config import Settings
from app.db.schemas import (
    DocumentDetailResponse,
    DocumentListResponse,
    DocumentUploadResponse,
    IngestionStatusResponse,
)
from app.dependencies import get_app_settings, get_db_session
from app.ingestion.pipeline import run_ingestion_job
from app.runtime import safe_error_detail
from app.services.document_service import (
    DocumentIngestionConflictError,
    DocumentNotFoundError,
    DocumentServiceError,
    InvalidPdfUploadError,
    document_upload_response,
    get_document_detail,
    ingestion_status_response,
    list_documents,
    start_document_ingestion,
    upload_document,
)

router = APIRouter(prefix="/documents", tags=["documents"])

SettingsDependency = Annotated[Settings, Depends(get_app_settings)]
SessionDependency = Annotated[Session, Depends(get_db_session)]
UploadFileDependency = Annotated[UploadFile, File(...)]


@router.post("/upload", response_model=DocumentUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_document_route(
    response: Response,
    settings: SettingsDependency,
    session: SessionDependency,
    file: UploadFileDependency,
) -> DocumentUploadResponse:
    content = await file.read()
    try:
        result = upload_document(
            session=session,
            settings=settings,
            filename=file.filename,
            content_type=file.content_type,
            content=content,
        )
    except InvalidPdfUploadError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(exc),
        ) from exc
    finally:
        await file.close()

    if not result.created:
        response.status_code = status.HTTP_200_OK

    return document_upload_response(result.document)


@router.get("", response_model=DocumentListResponse)
def list_documents_route(session: SessionDependency) -> DocumentListResponse:
    return list_documents(session=session)


@router.get("/{document_id}", response_model=DocumentDetailResponse)
def get_document_route(document_id: int, session: SessionDependency) -> DocumentDetailResponse:
    try:
        return get_document_detail(session=session, document_id=document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/{document_id}/ingest",
    response_model=IngestionStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def ingest_document_route(
    document_id: int,
    background_tasks: BackgroundTasks,
    settings: SettingsDependency,
    session: SessionDependency,
) -> IngestionStatusResponse:
    try:
        result = start_document_ingestion(
            session=session,
            settings=settings,
            document_id=document_id,
        )
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DocumentIngestionConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except DocumentServiceError as exc:
        detail = safe_error_detail(exc, fallback="Failed to start ingestion job.")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail) from exc
    except SQLAlchemyError as exc:
        detail = safe_error_detail(exc, fallback="Failed to start ingestion job.")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail) from exc

    job_id = result.job.id
    if job_id is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ingestion job is missing an identifier.",
        )

    background_tasks.add_task(run_ingestion_job, settings, document_id, job_id)
    return ingestion_status_response(result.job, chunk_count=0)
