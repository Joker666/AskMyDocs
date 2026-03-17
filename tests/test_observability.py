from __future__ import annotations

from typing import Any, cast
from weakref import WeakSet

from fastapi import FastAPI, Request
from pydantic import SecretStr

from app.config import Settings
from app.observability import (
    _logfire_request_attributes_mapper,
    initialize_logfire_observability,
    instrument_fastapi_observability,
)


def make_settings(**overrides: Any) -> Settings:
    settings_cls = cast(Any, Settings)
    return settings_cls(
        _env_file=None,
        POSTGRES_HOST="localhost",
        POSTGRES_DB="askmydocs",
        POSTGRES_USER="postgres",
        POSTGRES_PASSWORD=SecretStr("postgres"),
        LOGFIRE_TOKEN=SecretStr("lf-write-token"),
        **overrides,
    )


def test_initialize_logfire_observability_instruments_pydantic_ai_once(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr("app.observability._LOGFIRE_PYDANTIC_AI_INSTRUMENTED", False)

    def fake_instrument_pydantic_ai(**kwargs: Any) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(
        "app.observability.logfire.instrument_pydantic_ai",
        fake_instrument_pydantic_ai,
    )

    settings = make_settings()
    initialize_logfire_observability(settings)
    initialize_logfire_observability(settings)

    assert calls == [
        {
            "include_content": True,
            "include_binary_content": False,
        }
    ]


def test_instrument_fastapi_observability_instruments_each_app_once(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr("app.observability._LOGFIRE_FASTAPI_APPS", WeakSet())

    def fake_instrument_fastapi(app: FastAPI, **kwargs: Any) -> None:
        calls.append({"app": app, **kwargs})

    monkeypatch.setattr("app.observability.logfire.instrument_fastapi", fake_instrument_fastapi)

    settings = make_settings()
    app = FastAPI()

    instrument_fastapi_observability(settings, app)
    instrument_fastapi_observability(settings, app)

    assert len(calls) == 1
    assert calls[0]["app"] is app
    assert calls[0]["capture_headers"] is False
    assert calls[0]["record_send_receive"] is False
    assert callable(calls[0]["request_attributes_mapper"])


def test_logfire_request_attributes_mapper_adds_request_metadata() -> None:
    request = Request(
        scope={
            "type": "http",
            "method": "GET",
            "path": "/documents/42",
            "headers": [
                (b"x-session-id", b"session-123"),
                (b"x-user-id", b"user-456"),
            ],
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 12345),
            "root_path": "",
            "http_version": "1.1",
        }
    )

    result = _logfire_request_attributes_mapper(request, {"values": {"document_id": 42}})

    assert result["http.path"] == "/documents/42"
    assert result["askmydocs.route_tag"] == "documents"
    assert result["request.session_id"] == "session-123"
    assert result["request.user_id"] == "user-456"
    assert result["values"] == {"document_id": 42}
