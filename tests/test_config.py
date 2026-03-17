from __future__ import annotations

from typing import Any, cast

import pytest
from pydantic import SecretStr, ValidationError

from app.config import Settings


def make_settings() -> Settings:
    settings_cls = cast(Any, Settings)
    return settings_cls(
        POSTGRES_HOST="localhost",
        POSTGRES_DB="askmydocs",
        POSTGRES_USER="postgres",
        POSTGRES_PASSWORD=SecretStr("postgres"),
    )


def test_settings_require_database_values(monkeypatch) -> None:
    for key in ("POSTGRES_HOST", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"):
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(ValidationError):
        settings_cls = cast(Any, Settings)
        settings_cls(_env_file=None)


def test_settings_build_database_url() -> None:
    settings = make_settings()

    assert settings.database_url == "postgresql+psycopg://postgres:postgres@localhost:5432/askmydocs"
    assert settings.embedding_dimension == 768


def test_logfire_requires_token_to_export() -> None:
    settings = make_settings()

    assert settings.logfire_is_configured is False
    assert settings.logfire_runtime_environment == "development"

    settings_cls = cast(Any, Settings)
    configured = settings_cls(
        POSTGRES_HOST="localhost",
        POSTGRES_DB="askmydocs",
        POSTGRES_USER="postgres",
        POSTGRES_PASSWORD=SecretStr("postgres"),
        LOGFIRE_TOKEN=SecretStr("lf-write-token"),
        LOGFIRE_ENVIRONMENT="staging",
    )

    assert configured.logfire_is_configured is True
    assert configured.logfire_runtime_environment == "staging"
