from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel

from app.config import Settings
from app.db.session import check_database_connection
from app.dependencies import get_app_settings

router = APIRouter(tags=["health"])
SettingsDependency = Annotated[Settings, Depends(get_app_settings)]


class ComponentCheck(BaseModel):
    status: Literal["ok", "error", "not_checked"]
    detail: str | None = None


class HealthChecks(BaseModel):
    app: ComponentCheck
    db: ComponentCheck
    proxy: ComponentCheck
    ollama: ComponentCheck


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
    proxy_check = ComponentCheck(status="not_checked")
    ollama_check = ComponentCheck(status="not_checked")

    try:
        check_database_connection(settings)
        db_check = ComponentCheck(status="ok")
        overall_status = "ok"
        response.status_code = status.HTTP_200_OK
    except Exception as exc:
        db_check = ComponentCheck(status="error", detail=_sanitize_error_message(exc))
        overall_status = "degraded"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthResponse(
        status=overall_status,
        checks=HealthChecks(
            app=app_check,
            db=db_check,
            proxy=proxy_check,
            ollama=ollama_check,
        ),
    )
