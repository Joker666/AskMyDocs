from __future__ import annotations

MAX_ERROR_DETAIL_LENGTH = 200


def safe_error_detail(
    error: Exception | str | None,
    *,
    fallback: str,
) -> str:
    if isinstance(error, Exception):
        raw_message = error.args[0] if error.args else str(error)
    else:
        raw_message = error

    message = str(raw_message or "").strip().splitlines()[0][:MAX_ERROR_DETAIL_LENGTH]
    return message or fallback
