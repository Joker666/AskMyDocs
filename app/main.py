from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request

from app.api import api_router
from app.config import Settings, get_settings
from app.logging import configure_logging, shutdown_logging
from app.observability import (
    get_langfuse_client,
    initialize_observability,
    propagate_request_trace_attributes,
    request_trace_input,
    response_trace_output,
    shutdown_observability,
)
from app.runtime import safe_error_detail


def ensure_runtime_dirs(settings: Settings) -> None:
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.parsed_dir).mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    configure_logging(settings)
    ensure_runtime_dirs(settings)
    initialize_observability(settings)
    try:
        yield
    finally:
        shutdown_observability(settings)
        shutdown_logging(settings)


def create_app() -> FastAPI:
    application = FastAPI(title="AskMyDocs", version="0.1.0", lifespan=lifespan)

    @application.middleware("http")
    async def observability_middleware(request: Request, call_next):
        settings = get_settings()
        client = get_langfuse_client(settings)
        if client is None:
            return await call_next(request)

        path = request.url.path or "/"
        with client.start_as_current_observation(
            name=f"http.request {request.method} {path}",
            as_type="span",
            input=request_trace_input(request),
            metadata={"component": "fastapi"},
        ) as span:
            with propagate_request_trace_attributes(settings, request):
                try:
                    response = await call_next(request)
                except Exception as exc:
                    span.update(
                        level="ERROR",
                        status_message=safe_error_detail(
                            exc,
                            fallback="Request handling failed.",
                        ),
                    )
                    raise

                span.update(output=response_trace_output(status_code=response.status_code))
                return response

    application.include_router(api_router)
    return application


app = create_app()
