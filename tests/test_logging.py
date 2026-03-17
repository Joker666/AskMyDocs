from __future__ import annotations

import logging
from typing import Any, cast

from pydantic import SecretStr

from app.config import Settings
from app.logging import KeyValueFormatter, configure_logging


def make_settings(**overrides: Any) -> Settings:
    settings_cls = cast(Any, Settings)
    return settings_cls(
        POSTGRES_HOST="localhost",
        POSTGRES_DB="askmydocs",
        POSTGRES_USER="postgres",
        POSTGRES_PASSWORD=SecretStr("postgres"),
        **overrides,
    )


def test_configure_logging_keeps_console_handler_without_logfire() -> None:
    settings = make_settings()
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_level = root_logger.level

    try:
        configure_logging(settings)

        assert len(root_logger.handlers) == 1
        assert isinstance(root_logger.handlers[0], logging.StreamHandler)
        assert isinstance(root_logger.handlers[0].formatter, KeyValueFormatter)
        assert root_logger.level == logging.INFO
    finally:
        root_logger.handlers.clear()
        for handler in original_handlers:
            root_logger.addHandler(handler)
        root_logger.setLevel(original_level)


def test_configure_logging_adds_logfire_handler_when_token_present(monkeypatch) -> None:
    settings = make_settings(
        LOGFIRE_TOKEN=SecretStr("lf-write-token"),
        LOGFIRE_SERVICE_VERSION="0.1.0",
        LOGFIRE_ENVIRONMENT="test",
    )
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_level = root_logger.level
    configure_calls: list[dict[str, Any]] = []
    handler_calls: list[dict[str, Any]] = []

    class DummyLogfireHandler(logging.Handler):
        def __init__(
            self,
            level: int | str = logging.NOTSET,
            fallback: logging.Handler | None = None,
        ):
            super().__init__(level=level)
            handler_calls.append({"level": level, "fallback": fallback})

        def emit(self, record: logging.LogRecord) -> None:
            return None

    def fake_configure(**kwargs: Any) -> None:
        configure_calls.append(kwargs)

    monkeypatch.setattr("app.logging.logfire.configure", fake_configure)
    monkeypatch.setattr("app.logging.LogfireLoggingHandler", DummyLogfireHandler)

    try:
        configure_logging(settings)

        assert len(configure_calls) == 1
        assert configure_calls[0] == {
            "send_to_logfire": True,
            "token": "lf-write-token",
            "service_name": "askmydocs",
            "service_version": "0.1.0",
            "environment": "test",
            "console": False,
            "min_level": "INFO",
        }
        assert len(handler_calls) == 1
        assert handler_calls[0]["level"] == logging.INFO
        assert isinstance(handler_calls[0]["fallback"], logging.NullHandler)
        assert len(root_logger.handlers) == 2
        assert isinstance(root_logger.handlers[1], DummyLogfireHandler)
    finally:
        root_logger.handlers.clear()
        for handler in original_handlers:
            root_logger.addHandler(handler)
        root_logger.setLevel(original_level)
