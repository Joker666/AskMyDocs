from __future__ import annotations

import logging
import sys
from datetime import UTC, datetime

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


def configure_logging(level: str) -> None:
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(KeyValueFormatter())
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))
