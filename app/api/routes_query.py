from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.config import Settings
from app.db.schemas import QueryRequest, QueryResponse
from app.dependencies import get_app_settings, get_db_session
from app.services.query_service import (
    QueryAgentError,
    QueryDependencyError,
    QueryDocumentConflictError,
    QueryDocumentNotFoundError,
    query_documents,
)

router = APIRouter(tags=["query"])

SettingsDependency = Annotated[Settings, Depends(get_app_settings)]
SessionDependency = Annotated[Session, Depends(get_db_session)]


@router.post("/query", response_model=QueryResponse)
def query_route(
    request: QueryRequest,
    settings: SettingsDependency,
    session: SessionDependency,
) -> QueryResponse:
    try:
        return query_documents(session=session, settings=settings, request=request)
    except QueryDocumentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except QueryDocumentConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except QueryAgentError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except QueryDependencyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
