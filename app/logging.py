from __future__ import annotations

import logging
import sys
from datetime import UTC, datetime

import logfire
from logfire import LogfireLoggingHandler

from app.config import Settings

_STANDARD_RECORD_FIELDS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
}


class KeyValueFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created, UTC).isoformat()
        event = record.getMessage()
        parts = [
            f"time={timestamp}",
            f"level={record.levelname}",
            f"logger={_quote(record.name)}",
            f"event={_quote(event)}",
        ]

        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _STANDARD_RECORD_FIELDS and not key.startswith("_")
        }
        for key in sorted(extras):
            parts.append(f"{key}={_quote(extras[key])}")

        if record.exc_info:
            parts.append(f"exc_info={_quote(self.formatException(record.exc_info))}")

        return " ".join(parts)


def _quote(value: object) -> str:
    text = str(value)
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def configure_logging(settings: Settings) -> None:
    level_name = settings.log_level.upper()
    level = getattr(logging, level_name, logging.INFO)
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(KeyValueFormatter())
    root_logger.addHandler(handler)

    if settings.logfire_is_configured:
        logfire.configure(
            send_to_logfire=True,
            token=settings.logfire_token.get_secret_value() if settings.logfire_token else None,
            service_name=settings.logfire_service_name,
            service_version=settings.logfire_service_version,
            environment=settings.logfire_runtime_environment,
            console=False,
            min_level=level,
        )
        root_logger.addHandler(
            LogfireLoggingHandler(
                level=level,
                fallback=logging.NullHandler(),
            )
        )


def shutdown_logging(settings: Settings) -> None:
    if settings.logfire_is_configured:
        logfire.shutdown()
