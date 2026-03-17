from __future__ import annotations

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel

from app.agent.agent import check_anthropic_compat
from app.config import Settings
from app.db.session import check_database_connection
from app.dependencies import get_app_settings
from app.ingestion.embedder import check_ollama_native
from app.runtime import safe_error_detail

router = APIRouter(tags=["health"])
SettingsDependency = Annotated[Settings, Depends(get_app_settings)]
logger = logging.getLogger(__name__)


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
@router.get("/health", response_model=HealthResponse)
def healthcheck(
    response: Response,
    settings: SettingsDependency,
) -> HealthResponse:
    app_check = ComponentCheck(status="ok")
    overall_status = "ok"

    try:
        check_database_connection(settings)
        db_check = ComponentCheck(status="ok")
    except Exception as exc:
        detail = safe_error_detail(exc, fallback="Database connectivity check failed.")
        logger.warning("health_check_failed", extra={"component": "db", "detail": detail})
        db_check = ComponentCheck(status="error", detail=detail)
        overall_status = "degraded"

    try:
        check_anthropic_compat(settings)
        anthropic_compat_check = ComponentCheck(status="ok")
    except Exception as exc:
        detail = safe_error_detail(
            exc,
            fallback="Anthropic-compatible connectivity check failed.",
        )
        logger.warning(
            "health_check_failed",
            extra={"component": "anthropic_compat", "detail": detail},
        )
        anthropic_compat_check = ComponentCheck(
            status="error",
            detail=detail,
        )
        overall_status = "degraded"

    try:
        check_ollama_native(settings)
        ollama_native_check = ComponentCheck(status="ok")
    except Exception as exc:
        detail = safe_error_detail(exc, fallback="Ollama native connectivity check failed.")
        logger.warning(
            "health_check_failed",
            extra={"component": "ollama_native", "detail": detail},
        )
        ollama_native_check = ComponentCheck(status="error", detail=detail)
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
