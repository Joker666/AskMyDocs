from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlmodel import Session

from app.config import Settings
from app.db.schemas import DocumentDetailResponse, DocumentListResponse, DocumentUploadResponse
from app.dependencies import get_app_settings, get_db_session
from app.services.document_service import (
    DocumentNotFoundError,
    InvalidPdfUploadError,
    document_upload_response,
    get_document_detail,
    list_documents,
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
