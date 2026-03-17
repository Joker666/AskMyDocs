from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel

from app.config import Settings
from app.db.session import check_database_connection
from app.dependencies import get_app_settings
from app.ingestion.embedder import check_ollama_native

router = APIRouter(tags=["health"])
SettingsDependency = Annotated[Settings, Depends(get_app_settings)]


class ComponentCheck(BaseModel):
    status: Literal["ok", "error", "not_checked"]
    detail: str | None = None


class HealthChecks(BaseModel):
    app: ComponentCheck
    db: ComponentCheck
    anthropic_compat: ComponentCheck
    ollama_native: ComponentCheck


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    checks: HealthChecks


def _sanitize_error_message(error: Exception) -> str:
    message = str(error).strip().splitlines()[0]
    return message[:200] or error.__class__.__name__


@router.get("/health", response_model=HealthResponse)
def healthcheck(
    response: Response,
    settings: SettingsDependency,
) -> HealthResponse:
    app_check = ComponentCheck(status="ok")
    anthropic_compat_check = ComponentCheck(status="not_checked")
    overall_status = "ok"

    try:
        check_database_connection(settings)
        db_check = ComponentCheck(status="ok")
    except Exception as exc:
        db_check = ComponentCheck(status="error", detail=_sanitize_error_message(exc))
        overall_status = "degraded"

    try:
        check_ollama_native(settings)
        ollama_native_check = ComponentCheck(status="ok")
    except Exception as exc:
        ollama_native_check = ComponentCheck(status="error", detail=_sanitize_error_message(exc))
        overall_status = "degraded"

    response.status_code = (
        status.HTTP_200_OK
        if overall_status == "ok"
        else status.HTTP_503_SERVICE_UNAVAILABLE
    )

    return HealthResponse(
        status=overall_status,
        checks=HealthChecks(
            app=app_check,
            db=db_check,
            anthropic_compat=anthropic_compat_check,
            ollama_native=ollama_native_check,
        ),
    )
