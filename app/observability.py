from __future__ import annotations

import json
import logging
import os
from contextlib import nullcontext
from typing import Any, Literal

from fastapi import Request
from langfuse import Langfuse, get_client, propagate_attributes
from pydantic_ai import InstrumentationSettings

from app.config import Settings

logger = logging.getLogger(__name__)
_INITIALIZED_PUBLIC_KEYS: set[str] = set()
_PYTEST_DISABLED_LOGGED = False

ObservationType = Literal[
    "span",
    "generation",
    "agent",
    "tool",
    "chain",
    "retriever",
    "evaluator",
    "embedding",
    "guardrail",
]
SpanLevel = Literal["DEBUG", "DEFAULT", "WARNING", "ERROR"]

TRACE_TEXT_PREVIEW_LENGTH = 240
TRACE_LIST_PREVIEW_LENGTH = 20
SESSION_ID_HEADER = "x-session-id"
USER_ID_HEADER = "x-user-id"


def initialize_observability(settings: Settings) -> None:
    global _PYTEST_DISABLED_LOGGED
    if os.environ.get("PYTEST_CURRENT_TEST"):
        if not _PYTEST_DISABLED_LOGGED:
            logger.info(
                "langfuse_tracing_disabled",
                extra={"reason": "pytest"},
            )
            _PYTEST_DISABLED_LOGGED = True
        return

    if not settings.langfuse_is_configured:
        logger.info(
            "langfuse_tracing_disabled",
            extra={"reason": "missing_credentials_or_disabled"},
        )
        return

    public_key_secret = settings.langfuse_public_key
    secret_key = settings.langfuse_secret_key
    if public_key_secret is None or secret_key is None:
        return
    public_key = public_key_secret.get_secret_value()
    if public_key in _INITIALIZED_PUBLIC_KEYS:
        return

    Langfuse(
        public_key=public_key,
        secret_key=secret_key.get_secret_value(),
        base_url=settings.langfuse_base_url,
        environment=settings.langfuse_tracing_environment or settings.app_env,
        release=settings.langfuse_release,
        sample_rate=settings.langfuse_sample_rate,
        mask=_mask_trace_data,
    )
    _INITIALIZED_PUBLIC_KEYS.add(public_key)
    logger.info(
        "langfuse_tracing_enabled",
        extra={
            "base_url": settings.langfuse_base_url,
            "environment": settings.langfuse_tracing_environment or settings.app_env,
            "sample_rate": settings.langfuse_sample_rate,
        },
    )


def shutdown_observability(settings: Settings) -> None:
    if not settings.langfuse_is_configured:
        return

    public_key_secret = settings.langfuse_public_key
    if public_key_secret is None or settings.langfuse_secret_key is None:
        return
    public_key = public_key_secret.get_secret_value()
    get_client(public_key=public_key).shutdown()
    _INITIALIZED_PUBLIC_KEYS.discard(public_key)


def build_pydantic_ai_instrumentation(
    settings: Settings,
) -> InstrumentationSettings | bool:
    if not settings.langfuse_is_configured:
        return False

    initialize_observability(settings)
    return InstrumentationSettings(
        include_content=True,
        include_binary_content=False,
        version=4,
    )


def get_langfuse_client(settings: Settings) -> Langfuse | None:
    if not settings.langfuse_is_configured:
        return None

    initialize_observability(settings)
    return get_client()


def start_observation(
    settings: Settings,
    *,
    name: str,
    as_type: ObservationType = "span",
    input: Any | None = None,
    metadata: Any | None = None,
):
    client = get_langfuse_client(settings)
    if client is None:
        return nullcontext(None)
    return client.start_as_current_observation(
        name=name,
        as_type=as_type,
        input=input,
        metadata=metadata,
    )


def update_current_observation(
    settings: Settings,
    *,
    name: str | None = None,
    input: Any | None = None,
    output: Any | None = None,
    metadata: Any | None = None,
    level: SpanLevel | None = None,
    status_message: str | None = None,
) -> None:
    client = get_langfuse_client(settings)
    if client is None:
        return
    client.update_current_span(
        name=name,
        input=input,
        output=output,
        metadata=metadata,
        level=level,
        status_message=status_message,
    )


def propagate_request_trace_attributes(settings: Settings, request: Request):
    client = get_langfuse_client(settings)
    if client is None:
        return nullcontext(None)

    path = request.url.path or "/"
    return propagate_attributes(
        trace_name=f"{request.method} {path}",
        session_id=_header_value(request, SESSION_ID_HEADER),
        user_id=_header_value(request, USER_ID_HEADER),
        tags=["api", request.method.lower(), _route_tag(path)],
        metadata={
            "http.method": request.method,
            "http.path": path,
        },
    )


def request_trace_input(request: Request) -> dict[str, Any]:
    return {
        "method": request.method,
        "path": request.url.path,
        "query_params": dict(request.query_params),
    }


def response_trace_output(*, status_code: int) -> dict[str, int]:
    return {"status_code": status_code}


def preview_text(value: str, *, limit: int = TRACE_TEXT_PREVIEW_LENGTH) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 1]}..."


def safe_json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, default=str)
    except TypeError:
        return str(value)


def _header_value(request: Request, header_name: str) -> str | None:
    value = request.headers.get(header_name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped[:200] or None


def _route_tag(path: str) -> str:
    segments = [segment for segment in path.split("/") if segment]
    if not segments:
        return "root"
    return segments[0][:50]


def _mask_trace_data(*, data: Any, **_: dict[str, Any]) -> Any:
    if isinstance(data, bytes):
        return f"<{len(data)} bytes>"
    if isinstance(data, list):
        return [_mask_trace_data(data=item) for item in data]
    if isinstance(data, tuple):
        return [_mask_trace_data(data=item) for item in data]
    if isinstance(data, dict):
        return {str(key): _mask_trace_data(data=value) for key, value in data.items()}
    return data
